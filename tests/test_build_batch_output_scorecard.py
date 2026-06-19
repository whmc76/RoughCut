from pathlib import Path

import pytest

from scripts import build_batch_output_scorecard as scorecard


def test_score_platform_package_skips_soft_youtube_tags_penalty() -> None:
    packaging = {
        "platforms": {
            "youtube": {
                "titles": ["真实 YouTube 标题"],
                "description": "真实 YouTube 描述",
                "tags": [],
                "publish_ready": True,
                "live_publish_preflight": {"status": "ready", "blocking_reasons": []},
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["score"] == 100.0
    assert result["ready_count"] == 1
    assert result["blocked_count"] == 0
    assert result["manual_handoff_count"] == 0
    assert result["platform_scores"][0]["platform"] == "youtube"
    assert result["platform_scores"][0]["status"] == "ready"
    assert result["platform_scores"][0]["tag_count"] == 0


def test_score_platform_package_keeps_hard_tag_penalty_for_non_soft_platform() -> None:
    packaging = {
        "platforms": {
            "douyin": {
                "titles": ["真实抖音标题"],
                "description": "真实抖音描述",
                "tags": [],
                "publish_ready": True,
                "live_publish_preflight": {"status": "ready", "blocking_reasons": []},
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["score"] == 85.0
    assert result["platform_scores"][0]["platform"] == "douyin"
    assert result["platform_scores"][0]["status"] == "ready"
    assert result["platform_scores"][0]["tag_count"] == 0


def test_score_platform_package_reports_manual_handoff_platforms_separately() -> None:
    packaging = {
        "platforms": {
            "wechat-channels": {
                "titles": [],
                "description": "",
                "tags": [],
                "publish_ready": False,
                "manual_handoff_only": True,
                "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
                "live_publish_preflight": {
                    "status": "manual_handoff",
                    "blocking_reasons": ["需要人工登录"],
                },
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["score"] == 100.0
    assert result["manual_handoff_count"] == 1
    assert result["ready_count"] == 0
    assert result["blocked_count"] == 0
    assert "人工接管 1 个" in result["summary"]
    assert result["platform_scores"][0]["platform"] == "wechat-channels"
    assert result["platform_scores"][0]["status"] == "manual_handoff"


def test_score_platform_package_blocks_stale_publish_ready_true_when_preflight_is_blocked() -> None:
    packaging = {
        "platforms": {
            "douyin": {
                "titles": ["真实抖音标题"],
                "description": "真实抖音描述",
                "tags": ["开箱"],
                "publish_ready": True,
                "live_publish_preflight": {
                    "status": "blocked",
                    "blocking_reasons": ["缺少封面"],
                    "missing_required_surfaces": ["cover"],
                },
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["ready_count"] == 0
    assert result["blocked_count"] == 1
    assert result["platform_scores"][0]["platform"] == "douyin"
    assert result["platform_scores"][0]["status"] == "blocked"


def test_score_editing_prefers_variant_bundle_cut_analysis_and_refine_summary() -> None:
    result = scorecard._score_editing_with_variant_bundle(
        {"keep_ratio": 0.5, "quality_issue_codes": []},
        {
            "analysis": {
                "accepted_cuts": [],
                "llm_cut_review": {"reviewed": False, "candidate_count": 0},
            }
        },
        {"editing_accents": {"transitions": {"boundary_indexes": [1, 2]}}},
        {
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "cut_analysis_summary": {"accepted_cut_count": 0},
                    "llm_cut_review": {"reviewed": True, "candidate_count": 4},
                    "refine_decision_summary": {"mode": "auto_refine", "candidate_total": 6, "rule_auto_apply_cut_count": 3},
                }
            },
        },
    )

    assert result["status"] == "done"
    assert "accepted_cuts=3" in result["summary"]
    assert "llm_cut_review=yes" in result["summary"]
    assert "refine_mode=auto_refine" in result["summary"]
    assert "refine_candidates=6" in result["summary"]


def test_score_editing_legacy_render_plan_reads_nested_packaging_timeline_transitions() -> None:
    result = scorecard._score_editing(
        {"keep_ratio": 0.5, "quality_issue_codes": []},
        {"analysis": {"accepted_cuts": []}},
        {
            "packaging_timeline": {
                "editing_accents": {"transitions": {"boundary_indexes": [1, 2, 3]}},
            }
        },
    )

    assert "transition_boundaries=3" in result["summary"]


def test_score_viewing_experience_penalizes_viewer_facing_polish_issues() -> None:
    result = scorecard._score_viewing_experience(
        job={
            "keep_ratio": 0.96,
            "output_duration_sec": 240.0,
            "output_path": "E:/missing.mp4",
        },
        render_outputs={
            "packaged_mp4": "E:/missing.mp4",
            "quality_checks": {
                "subtitle_sync": {"status": "warning"},
            },
        },
        subtitle_quality={
            "warning_reasons": ["短碎句率偏高 2.00%"],
            "blocking_reasons": [],
            "metrics": {
                "short_fragment_count": 6,
                "generic_word_split_count": 1,
                "filler_count": 1,
                "low_signal_count": 0,
            },
        },
        render_plan={
            "subtitles": {"section_profiles": []},
            "editing_accents": {
                "effect_policy": {"preserve_color": False},
                "emphasis_overlays": [{"text": "a"} for _ in range(12)],
                "sound_effects": [{"start_time": 1.0} for _ in range(12)],
                "transitions": {"boundary_indexes": list(range(12))},
            },
        },
        variant_bundle={
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "blocking_high_risk_cut_count": 0,
                    "high_risk_cuts": [
                        {"review_priority": "advisory", "blocking": False},
                        {"review_priority": "advisory", "blocking": False},
                    ],
                    "cut_analysis_summary": {"accepted_cut_count": 0},
                    "refine_decision_summary": {},
                }
            },
        },
        version_scores=[
            {"name": "packaged", "score": 62.0, "status": "missing"},
            {"name": "plain", "score": 96.0, "status": "done"},
        ],
        editing_risk_metrics={
            "high_risk_cut_count": 2,
            "blocking_high_risk_cuts": False,
        },
    )

    assert result["score"] < 90.0
    assert result["status"] == "fail"
    assert [component["name"] for component in result["components"]] == [
        "subtitle_readability",
        "pacing_and_cut_flow",
        "visual_polish_and_restraint",
        "delivery_stability",
    ]
    assert any("短碎句" in reason for reason in result["components"][0]["reasons"])
    assert any("保留比偏高" in reason for reason in result["components"][1]["reasons"])
    assert any("包装效果未声明保色" in reason for reason in result["components"][2]["reasons"])
    assert any("字幕同步 warning" in reason for reason in result["components"][3]["reasons"])


def test_score_viewing_experience_passes_clean_watching_signals() -> None:
    result = scorecard._score_viewing_experience(
        job={"keep_ratio": 0.82, "output_duration_sec": 300.0, "output_path": __file__},
        render_outputs={
            "packaged_mp4": __file__,
            "quality_checks": {
                "subtitle_sync": {"status": "ok"},
                "final_render_subtitle_asr_alignment": {
                    "gate_pass": True,
                    "audit": {"matched_count": 20, "event_count": 20},
                },
            },
        },
        subtitle_quality={
            "warning_reasons": [],
            "blocking_reasons": [],
            "metrics": {
                "short_fragment_count": 1,
                "generic_word_split_count": 0,
                "filler_count": 0,
                "low_signal_count": 0,
            },
        },
        render_plan={
            "subtitles": {"section_profiles": [{"role": "hook"}, {"role": "body"}]},
            "editing_accents": {
                "effect_policy": {"preserve_color": True},
                "emphasis_overlays": [{"text": "重点"}],
                "sound_effects": [{"start_time": 1.0}],
                "transitions": {"boundary_indexes": [1]},
            },
        },
        variant_bundle={
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "blocking_high_risk_cut_count": 0,
                    "high_risk_cuts": [],
                    "cut_analysis_summary": {"accepted_cut_count": 4},
                    "refine_decision_summary": {},
                }
            },
        },
        version_scores=[{"name": "packaged", "score": 100.0, "status": "done"}],
        editing_risk_metrics={"high_risk_cut_count": 0, "blocking_high_risk_cuts": False},
    )

    assert result["score"] >= 95.0
    assert result["status"] == "pass"
    assert any("字幕读感干净" in reason for reason in result["components"][0]["reasons"])
    assert any("最终成片音频 Qwen3" in reason for reason in result["components"][0]["reasons"])


def test_score_viewing_experience_blocks_perfect_score_without_final_audio_asr_audit() -> None:
    result = scorecard._score_viewing_experience(
        job={"keep_ratio": 0.82, "output_duration_sec": 300.0, "output_path": __file__},
        render_outputs={
            "packaged_mp4": __file__,
            "quality_checks": {"subtitle_sync": {"status": "ok"}},
        },
        subtitle_quality={
            "warning_reasons": [],
            "blocking_reasons": [],
            "metrics": {
                "short_fragment_count": 0,
                "generic_word_split_count": 0,
                "filler_count": 0,
                "low_signal_count": 0,
            },
        },
        render_plan={
            "subtitles": {"section_profiles": [{"role": "hook"}]},
            "editing_accents": {"effect_policy": {"preserve_color": True}},
        },
        variant_bundle=None,
        version_scores=[{"name": "packaged", "score": 100.0, "status": "done"}],
        editing_risk_metrics={"high_risk_cut_count": 0, "blocking_high_risk_cuts": False},
    )

    subtitle_component = next(item for item in result["components"] if item["name"] == "subtitle_readability")
    assert subtitle_component["score"] <= 58.0
    assert any("缺少最终成片音频 Qwen3" in reason for reason in subtitle_component["reasons"])


def test_score_viewing_experience_penalizes_failed_final_audio_asr_audit() -> None:
    result = scorecard._score_viewing_experience(
        job={"keep_ratio": 0.82, "output_duration_sec": 300.0, "output_path": __file__},
        render_outputs={
            "packaged_mp4": __file__,
            "quality_checks": {
                "subtitle_sync": {"status": "ok"},
                "final_render_subtitle_asr_alignment": {
                    "gate_pass": False,
                    "audit": {
                        "event_count": 20,
                        "matched_count": 14,
                        "unmatched_count": 6,
                        "bad_drift_count": 9,
                        "avg_abs_start_drift_sec": 2.4,
                        "avg_abs_end_drift_sec": 1.8,
                    },
                },
            },
        },
        subtitle_quality={"warning_reasons": [], "blocking_reasons": [], "metrics": {}},
        render_plan={
            "subtitles": {"section_profiles": [{"role": "hook"}]},
            "editing_accents": {"effect_policy": {"preserve_color": True}},
        },
        variant_bundle=None,
        version_scores=[{"name": "packaged", "score": 100.0, "status": "done"}],
        editing_risk_metrics={"high_risk_cut_count": 0, "blocking_high_risk_cuts": False},
    )

    subtitle_component = next(item for item in result["components"] if item["name"] == "subtitle_readability")
    delivery_component = next(item for item in result["components"] if item["name"] == "delivery_stability")
    assert subtitle_component["score"] <= 44.0
    assert any("最终成片音频 Qwen3 字幕校准失败" in reason for reason in subtitle_component["reasons"])
    assert any("最终成片音频 Qwen3 字幕审计未通过" in reason for reason in delivery_component["reasons"])


def test_score_viewing_experience_penalizes_variant_subtitle_timeline_validation() -> None:
    result = scorecard._score_viewing_experience(
        job={"keep_ratio": 0.82, "output_duration_sec": 300.0, "output_path": __file__},
        render_outputs={
            "packaged_mp4": __file__,
            "quality_checks": {"subtitle_sync": {"status": "ok"}},
        },
        subtitle_quality={
            "warning_reasons": [],
            "blocking_reasons": [],
            "metrics": {
                "short_fragment_count": 0,
                "generic_word_split_count": 0,
                "filler_count": 0,
                "low_signal_count": 0,
            },
        },
        render_plan={"subtitles": {"section_profiles": [{"role": "body"}]}, "editing_accents": {"effect_policy": {"preserve_color": True}}},
        variant_bundle={
            "validation": {
                "status": "warning",
                "issues": ["packaged: subtitle events are not monotonic at index 14"],
            },
            "variants": {"packaged": {"segments": []}},
        },
        version_scores=[{"name": "packaged", "score": 100.0, "status": "done"}],
        editing_risk_metrics={"high_risk_cut_count": 0, "blocking_high_risk_cuts": False},
    )

    subtitle_component = next(item for item in result["components"] if item["name"] == "subtitle_readability")
    assert subtitle_component["score"] < 90.0
    assert any("字幕时间线校验异常" in reason for reason in subtitle_component["reasons"])


def test_score_avatar_prefers_runtime_render_diagnostics_when_render_outputs_missing_avatar_result() -> None:
    result = scorecard._score_avatar(
        {
            "integration_mode": "picture_in_picture",
            "provider": "heygem",
            "voice_provider": "runninghub",
            "render_execution": {"status": "deferred_to_render"},
        },
        {},
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_call_timeout",
                "reason_category": "call_timeout",
                "detail": "数字人渲染未完成，已自动回退普通成片：avatar_full_track_call_timeout>180.0s",
                "retryable": True,
            }
        },
    )

    assert result == {
        "score": 57.0,
        "grade": "E",
        "status": "degraded",
        "summary": "avatar_result=degraded:avatar_full_track_call_timeout(call_timeout)；集成模式 picture_in_picture；render_execution=deferred_to_render；未生成独立口播分段，当前为全轨透传/弱插入模式",
        "provider": "heygem",
        "voice_provider": "runninghub",
    }


def test_score_avatar_treats_not_configured_skip_as_not_applicable() -> None:
    result = scorecard._score_avatar(
        {
            "integration_mode": "",
            "provider": "heygem",
            "voice_provider": "runninghub",
            "render_execution": {
                "status": "skipped",
                "reason": "creator_avatar_binding_missing",
            },
        },
        {},
        {
            "avatar_result": {
                "status": "skipped",
                "reason": "creator_avatar_binding_missing",
                "reason_category": "not_configured",
                "detail": "未配置可用数字人 presenter，跳过数字人渲染；普通成片不受影响。",
            }
        },
    )

    assert result == {
        "score": None,
        "grade": "N/A",
        "status": "not_configured",
        "summary": "avatar_result=skipped:creator_avatar_binding_missing(not_configured)",
        "provider": "heygem",
        "voice_provider": "runninghub",
    }


def test_score_avatar_infers_reason_category_from_legacy_reason() -> None:
    result = scorecard._score_avatar(
        {
            "integration_mode": "picture_in_picture",
            "provider": "heygem",
            "voice_provider": "runninghub",
            "render_execution": {"status": "deferred_to_render"},
        },
        {},
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_provider_response_error",
                "detail": "provider 500",
                "retryable": False,
            }
        },
    )

    assert "avatar_full_track_provider_response_error(provider_error)" in result["summary"]


def test_score_avatar_infers_reason_category_from_legacy_batch_job_diagnostics() -> None:
    result = scorecard._score_avatar(
        {
            "integration_mode": "picture_in_picture",
            "provider": "heygem",
            "voice_provider": "runninghub",
            "render_execution": {"status": "deferred_to_render"},
        },
        {},
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_call_timeout",
                "detail": "timeout",
                "retryable": True,
            }
        },
    )

    assert "avatar_full_track_call_timeout(call_timeout)" in result["summary"]


def test_score_avatar_falls_back_to_typed_render_step_reason_when_avatar_result_missing() -> None:
    result = scorecard._score_avatar(
        {
            "integration_mode": "picture_in_picture",
            "provider": "heygem",
            "voice_provider": "runninghub",
            "render_execution": {"status": "deferred_to_render"},
        },
        {},
        {
            "render_step": {
                "status": "failed",
                "reason": "render_timeout_process",
                "detail": "TimeoutError: render exceeded 300s",
            }
        },
    )

    assert result == {
        "score": 57.0,
        "grade": "E",
        "status": "blocked",
        "summary": "avatar_result=blocked:render_timeout_process(render_timeout_process)；集成模式 picture_in_picture；render_execution=deferred_to_render；未生成独立口播分段，当前为全轨透传/弱插入模式",
        "provider": "heygem",
        "voice_provider": "runninghub",
    }


def test_score_avatar_prefers_failed_render_step_over_weak_missing_avatar_fallback() -> None:
    result = scorecard._score_avatar(
        {
            "integration_mode": "picture_in_picture",
            "provider": "heygem",
            "voice_provider": "runninghub",
            "render_execution": {"status": "deferred_to_render"},
        },
        {},
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "missing_avatar_render",
                "detail": "没有拿到可用数字人视频，已自动回退普通成片。",
            },
            "render_step": {
                "status": "failed",
                "reason": "render_timeout_process",
                "detail": "TimeoutError: render exceeded 300s",
            },
        },
    )

    assert result == {
        "score": 57.0,
        "grade": "E",
        "status": "blocked",
        "summary": "avatar_result=blocked:render_timeout_process(render_timeout_process)；集成模式 picture_in_picture；render_execution=deferred_to_render；未生成独立口播分段，当前为全轨透传/弱插入模式",
        "provider": "heygem",
        "voice_provider": "runninghub",
    }


def test_editing_risk_metrics_reads_variant_bundle_and_issue_codes() -> None:
    result = scorecard._editing_risk_metrics(
        {"quality_issue_codes": ["editing_high_risk_cuts_blocking", "editing_manual_confirm_heavy_blocking"]},
        {},
        None,
        {
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "high_risk_cuts": [{"start": 1.0, "end": 2.0}, {"start": 3.0, "end": 4.0}],
                    "llm_cut_review": {"reviewed": False, "candidate_count": 2},
                    "multimodal_trim_review_summary": {"candidate_count": 2, "pending_count": 1},
                    "refine_decision_summary": {"candidate_auto_apply": 3, "candidate_manual_confirm": 2},
                }
            },
        },
    )

    assert result == {
        "source": "variant_timeline_bundle",
        "source_reason": "variant_bundle_available",
        "high_risk_cut_count": 2,
        "auto_apply_candidate_count": 3,
        "manual_confirm_count": 2,
        "multimodal_pending_count": 1,
        "llm_reviewed": False,
        "llm_error": "",
        "llm_provider_degraded": False,
        "blocking_high_risk_cuts": True,
        "blocking_manual_confirm_heavy": False,
    }


def test_editing_risk_metrics_uses_pre_render_variant_bundle_without_media_variants() -> None:
    result = scorecard._editing_risk_metrics(
        {"status": "partial", "quality_issue_codes": []},
        {},
        {
            "accepted_cut_count": 99,
            "manual_confirm_candidate_count": 99,
            "multimodal_trim_review_summary": {"pending_count": 99},
        },
        {
            "variants": {},
            "timeline_rules": {
                "diagnostics": {
                    "high_risk_cuts": [{"start": 1.0, "end": 2.0}],
                    "llm_cut_review": {"reviewed": True, "candidate_count": 1},
                    "multimodal_trim_review_summary": {"candidate_count": 1, "pending_count": 0},
                    "refine_decision_summary": {"candidate_manual_confirm": 3},
                }
            },
        },
    )

    assert result == {
        "source": "variant_timeline_bundle",
        "source_reason": "variant_bundle_available",
        "high_risk_cut_count": 1,
        "auto_apply_candidate_count": 0,
        "manual_confirm_count": 3,
        "multimodal_pending_count": 0,
        "llm_reviewed": True,
        "llm_error": "",
        "llm_provider_degraded": False,
        "blocking_high_risk_cuts": True,
        "blocking_manual_confirm_heavy": False,
    }


def test_editing_risk_metrics_falls_back_to_legacy_editorial_and_cut_analysis() -> None:
    result = scorecard._editing_risk_metrics(
        {
            "status": "partial",
            "quality_issue_codes": [],
            "live_stage_validations": [
                {"stage": "render", "status": "skipped", "summary": "render 因 stop_after 未执行", "issue_codes": []},
            ],
        },
        {
            "analysis": {
                "accepted_cuts": [
                    {"start": 1.0, "end": 2.0, "boundary_keep_energy": 1.1},
                    {"start": 3.0, "end": 4.0, "boundary_keep_energy": 0.4},
                ],
                "llm_cut_review": {"reviewed": True, "candidate_count": 1},
            }
        },
        {
            "accepted_cut_count": 2,
            "auto_apply_candidate_count": 1,
            "manual_confirm_candidate_count": 2,
            "multimodal_trim_review_summary": {"pending_count": 1},
        },
        None,
    )

    assert result == {
        "source": "legacy_editorial_cut_analysis",
        "source_reason": "pre_render_stop_without_variant_bundle",
        "high_risk_cut_count": 1,
        "auto_apply_candidate_count": 1,
        "manual_confirm_count": 2,
        "multimodal_pending_count": 1,
        "llm_reviewed": True,
        "llm_error": "",
        "llm_provider_degraded": False,
        "blocking_high_risk_cuts": False,
        "blocking_manual_confirm_heavy": False,
    }


def test_editing_risk_metrics_legacy_path_ignores_stale_issue_codes_when_shared_gate_disagrees() -> None:
    result = scorecard._editing_risk_metrics(
        {
            "status": "partial",
            "quality_issue_codes": ["editing_manual_confirm_heavy_blocking"],
            "live_stage_validations": [
                {"stage": "render", "status": "skipped", "summary": "render 因 stop_after 未执行", "issue_codes": []},
            ],
        },
        {
            "analysis": {
                "accepted_cuts": [
                    {"start": 1.0, "end": 2.0, "boundary_keep_energy": 0.4},
                ],
                "llm_cut_review": {"reviewed": True, "candidate_count": 1},
            }
        },
        {
            "accepted_cut_count": 1,
            "auto_apply_candidate_count": 1,
            "manual_confirm_candidate_count": 2,
            "multimodal_trim_review_summary": {"pending_count": 0},
        },
        None,
    )

    assert result["source"] == "legacy_editorial_cut_analysis"
    assert result["blocking_high_risk_cuts"] is False
    assert result["blocking_manual_confirm_heavy"] is False


def test_editing_risk_metrics_exposes_llm_provider_degraded_state() -> None:
    result = scorecard._editing_risk_metrics(
        {"quality_issue_codes": ["editing_high_risk_cuts_provider_degraded"]},
        {},
        None,
        {
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "high_risk_cuts": [{"start": 1.0, "end": 2.0}],
                    "llm_cut_review": {
                        "reviewed": False,
                        "candidate_count": 1,
                        "error": "llm_cut_review_failed",
                    },
                    "multimodal_trim_review_summary": {"candidate_count": 1, "pending_count": 1},
                    "refine_decision_summary": {"candidate_manual_confirm": 1},
                }
            },
        },
    )

    assert result == {
        "source": "variant_timeline_bundle",
        "source_reason": "variant_bundle_available",
        "high_risk_cut_count": 1,
        "auto_apply_candidate_count": 0,
        "manual_confirm_count": 1,
        "multimodal_pending_count": 1,
        "llm_reviewed": False,
        "llm_error": "llm_cut_review_failed",
        "llm_provider_degraded": True,
        "blocking_high_risk_cuts": False,
        "blocking_manual_confirm_heavy": False,
    }


def test_build_version_scores_reads_current_render_quality_check_shape() -> None:
    result = scorecard._build_version_scores(
        {
            "packaged_mp4": "E:/packaged.mp4",
            "plain_mp4": "E:/plain.mp4",
            "avatar_mp4": "E:/avatar.mp4",
            "ai_effect_mp4": "E:/ai_effect.mp4",
            "quality_checks": {
                "subtitle_sync": {"status": "ok", "message": "packaged aligned"},
                "plain_subtitle_sync": {"status": "warning", "message": "plain drift"},
                "avatar_subtitle_sync": {"status": "ok", "message": "avatar aligned"},
                "ai_effect_subtitle_sync": {"status": "warning", "message": "ai drift"},
            },
        }
    )

    assert [item["name"] for item in result] == ["packaged", "plain", "avatar", "ai_effect"]
    assert [item["status"] for item in result] == ["missing", "missing", "missing", "missing"]
    assert "字幕同步质检通过" in result[0]["reasons"]
    assert "字幕同步质检存在 warning" in result[1]["reasons"]
    assert "字幕同步质检通过" in result[2]["reasons"]
    assert "字幕同步质检存在 warning" in result[3]["reasons"]


def test_variant_score_penalizes_severe_subtitle_timing_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scorecard, "_file_exists", lambda _path: True)

    result = scorecard._summarize_variant_score(
        "packaged",
        "E:/packaged.mp4",
        {
            "status": "warning",
            "warning_codes": [
                "subtitle_burst_density_detected",
                "subtitle_short_flash_detected",
            ],
        },
    )

    assert result["score"] <= 62.0
    assert "warning_codes=subtitle_burst_density_detected, subtitle_short_flash_detected" in result["reasons"]


def test_viewing_experience_penalizes_subtitle_timing_structure_warnings() -> None:
    result = scorecard._score_viewing_experience(
        job={"output_duration_sec": 60.0, "output_path": "E:/packaged.mp4", "keep_ratio": 0.7},
        render_outputs={
            "packaged_mp4": "E:/packaged.mp4",
            "quality_checks": {
                "subtitle_sync": {
                    "status": "warning",
                    "warning_codes": ["subtitle_burst_density_detected"],
                }
            },
        },
        subtitle_quality={"metrics": {}, "warning_reasons": [], "blocking_reasons": []},
        render_plan={"subtitles": {"section_profiles": [{"role": "detail"}]}},
        variant_bundle=None,
        version_scores=[],
        editing_risk_metrics={},
    )

    subtitle_component = next(item for item in result["components"] if item["name"] == "subtitle_readability")
    assert subtitle_component["score"] < 85.0
    assert any("字幕时间结构异常" in reason for reason in subtitle_component["reasons"])


def test_live_readiness_summary_collects_failed_checks() -> None:
    result = scorecard._live_readiness_summary(
        {
            "live_readiness": {
                "gate_passed": False,
                "status": "blocked",
                "checks": {
                    "required_checks_contract": {"passed": False},
                    "risk_alignment_contract": {"passed": True},
                },
            }
        }
    )

    assert result == {
        "gate_passed": False,
        "status": "blocked",
        "failed_checks": ["required_checks_contract"],
    }


def test_render_markdown_includes_aggregate_and_job_level_editing_risk_metrics() -> None:
    content = scorecard.render_markdown(
        {
            "created_at": "2026-06-11T00:00:00Z",
            "job_count": 1,
            "aggregate_dimension_scores": [],
            "aggregate_stage_scores": [],
            "live_readiness": {
                "gate_passed": False,
                "status": "blocked",
                "failed_checks": ["required_checks_contract"],
            },
                "aggregate_risk_metrics": {
                    "high_risk_cut_count": 3,
                    "auto_apply_candidate_count": 4,
                    "manual_confirm_count": 2,
                    "multimodal_pending_count": 1,
                    "llm_reviewed_job_count": 0,
                    "llm_provider_degraded_job_count": 0,
                    "blocking_high_risk_job_count": 1,
                    "blocking_manual_confirm_job_count": 1,
                    "variant_bundle_job_count": 0,
                    "legacy_risk_job_count": 1,
                },
            "jobs": [
                {
                    "source_name": "demo.mp4",
                    "output_path": "E:/demo_out.mp4",
                    "overall_video_quality": {"score": 90.0, "grade": "A", "summary": "ok"},
                    "viewing_experience": {"score": 82.0, "grade": "B", "summary": "观感偏拖"},
                    "subtitle_quality": {"score": 88.0, "grade": "B", "summary": "ok"},
                    "multi_platform_package": {"score": 90.0, "grade": "A", "summary": "ok"},
                    "avatar": {"score": 90.0, "grade": "A", "summary": "ok"},
                    "tts": {"score": 90.0, "grade": "A", "summary": "ok"},
                    "ai_effects": {"score": 90.0, "grade": "A", "summary": "ok"},
                    "subtitle_effects": {"score": 90.0, "grade": "A", "summary": "ok"},
                    "editing": {"score": 80.0, "grade": "B", "summary": "ok"},
                        "editing_risk_metrics": {
                            "source": "legacy_editorial_cut_analysis",
                            "source_reason": "pre_render_stop_without_variant_bundle",
                            "high_risk_cut_count": 3,
                            "auto_apply_candidate_count": 4,
                            "manual_confirm_count": 2,
                            "multimodal_pending_count": 1,
                            "llm_reviewed": False,
                            "llm_error": "",
                            "llm_provider_degraded": False,
                            "blocking_high_risk_cuts": True,
                            "blocking_manual_confirm_heavy": True,
                        },
                    "version_scores": [],
                    "live_stage_scores": [],
                }
            ],
        },
        Path("E:/batch_report.json"),
    )

    assert "## Aggregate Risk Metrics" in content
    assert "## Live Readiness" in content
    assert "- gate_passed: false" in content
    assert "- status: blocked" in content
    assert "- failed_checks: required_checks_contract" in content
    assert "- viewing_experience: 82.0 (B) | 观感偏拖" in content
    assert "- high_risk_cut_count: 3" in content
    assert "- blocking_manual_confirm_job_count: 1" in content
    assert "- auto_apply_candidate_count" not in content
    assert "- variant_bundle_job_count" not in content
    assert "- llm_provider_degraded_job_count" not in content
    assert "editing_risk_metrics: source=legacy_editorial_cut_analysis, high_risk_cut_count=3, manual_confirm_count=2, multimodal_pending_count=1, blocking_high_risk_cuts=true, blocking_manual_confirm_heavy=true" in content


def test_render_markdown_hides_render_dependent_sections_for_pre_render_partial_runs() -> None:
    content = scorecard.render_markdown(
        {
            "created_at": "2026-06-12T00:00:00Z",
            "job_count": 1,
            "aggregate_dimension_scores": [
                {"dimension": "overall_video_quality", "score": 100.0, "grade": "A"},
                {"dimension": "avatar", "score": 57.0, "grade": "E"},
                {"dimension": "ai_effects", "score": 0.0, "grade": "E"},
                {"dimension": "editing", "score": 86.0, "grade": "B"},
            ],
            "aggregate_stage_scores": [
                {"stage": "content_profile", "score": 100.0, "grade": "A"},
                {"stage": "edit_plan", "score": 75.0, "grade": "C"},
                {"stage": "render", "score": 0.0, "grade": "E"},
                {"stage": "platform_package", "score": 0.0, "grade": "E"},
            ],
            "aggregate_risk_metrics": {
                "high_risk_cut_count": 0,
                "auto_apply_candidate_count": 2,
                "manual_confirm_count": 0,
                "multimodal_pending_count": 0,
                "blocking_high_risk_job_count": 0,
                "blocking_manual_confirm_job_count": 0,
            },
            "jobs": [
                {
                    "source_name": "demo.mp4",
                    "output_path": "",
                    "overall_video_quality": {"score": 100.0, "grade": "A", "summary": "ok"},
                    "subtitle_quality": {"score": 100.0, "grade": "A", "summary": "ok"},
                    "multi_platform_package": {"score": None, "grade": "N/A", "summary": "未发现多平台包装产物"},
                    "avatar": {"score": 57.0, "grade": "E", "summary": "avatar skipped"},
                    "tts": {"score": None, "grade": "N/A", "summary": "tts skipped"},
                    "ai_effects": {"score": 0.0, "grade": "E", "summary": "AI 特效版本未生成"},
                    "subtitle_effects": {"score": 90.0, "grade": "A", "summary": "ok"},
                    "editing": {"score": 86.0, "grade": "B", "summary": "ok"},
                    "editing_risk_metrics": {
                        "source": "variant_timeline_bundle",
                        "high_risk_cut_count": 0,
                        "auto_apply_candidate_count": 2,
                        "manual_confirm_count": 0,
                        "multimodal_pending_count": 0,
                        "blocking_high_risk_cuts": False,
                        "blocking_manual_confirm_heavy": False,
                    },
                    "version_scores": [],
                    "live_stage_scores": [
                        {"stage": "content_profile", "score": 100.0, "grade": "A", "status": "pass", "summary": "ok"},
                        {"stage": "edit_plan", "score": 75.0, "grade": "C", "status": "warn", "summary": "ok"},
                        {"stage": "render", "score": 0.0, "grade": "E", "status": "skipped", "summary": "render skipped"},
                        {"stage": "platform_package", "score": 0.0, "grade": "E", "status": "skipped", "summary": "package skipped"},
                    ],
                }
            ],
        },
        Path("E:/batch_report.json"),
    )

    assert "- avatar:" not in content
    assert "- ai_effects:" not in content
    assert "- multi_platform_package:" not in content
    assert "- version_scores:" not in content
    assert "- render: 0.0 (E)" not in content
    assert "- platform_package: 0.0 (E)" not in content


def test_render_markdown_focuses_failed_jobs_on_delivery_blockers() -> None:
    content = scorecard.render_markdown(
        {
            "created_at": "2026-06-12T00:00:00Z",
            "job_count": 1,
            "aggregate_dimension_scores": [
                {"dimension": "overall_video_quality", "score": 100.0, "grade": "A"},
                {"dimension": "subtitle_quality", "score": 100.0, "grade": "A"},
                {"dimension": "avatar", "score": 57.0, "grade": "E"},
                {"dimension": "editing", "score": 88.0, "grade": "B"},
            ],
            "aggregate_stage_scores": [
                {"stage": "probe", "score": 100.0, "grade": "A"},
                {"stage": "edit_plan", "score": 100.0, "grade": "A"},
                {"stage": "render", "score": 0.0, "grade": "E"},
                {"stage": "final_review", "score": 0.0, "grade": "E"},
            ],
            "aggregate_risk_metrics": {
                "high_risk_cut_count": 0,
                "auto_apply_candidate_count": 2,
                "manual_confirm_count": 0,
                "multimodal_pending_count": 0,
                "blocking_high_risk_job_count": 0,
                "blocking_manual_confirm_job_count": 0,
                "llm_provider_degraded_job_count": 0,
            },
            "live_readiness": {
                "gate_passed": False,
                "status": "fail",
                "failed_checks": ["render_end_state_stability"],
            },
            "jobs": [
                {
                    "source_name": "demo.mp4",
                    "output_path": "",
                    "overall_video_quality": {"score": 100.0, "grade": "A", "summary": "ok"},
                    "subtitle_quality": {"score": 100.0, "grade": "A", "summary": "ok"},
                    "multi_platform_package": {"score": None, "grade": "N/A", "status": "not_generated", "summary": "未发现多平台包装产物"},
                    "avatar": {"score": 57.0, "grade": "E", "status": "blocked", "summary": "avatar blocked"},
                    "tts": {"score": None, "grade": "N/A", "status": "skipped", "summary": "tts skipped"},
                    "ai_effects": {"score": 0.0, "grade": "E", "status": "missing", "summary": "ai missing"},
                    "subtitle_effects": {"score": 89.0, "grade": "B", "summary": "ok"},
                    "editing": {"score": 88.0, "grade": "B", "summary": "ok"},
                    "editing_risk_metrics": {
                        "source": "variant_timeline_bundle",
                        "high_risk_cut_count": 0,
                        "auto_apply_candidate_count": 2,
                        "manual_confirm_count": 0,
                        "multimodal_pending_count": 0,
                        "blocking_high_risk_cuts": False,
                        "blocking_manual_confirm_heavy": False,
                    },
                    "version_scores": [
                        {"name": "packaged", "score": None, "grade": "N/A", "status": "not_generated", "reasons": ["missing"]},
                    ],
                    "live_stage_scores": [
                        {"stage": "probe", "score": 100.0, "grade": "A", "status": "pass", "summary": "ok"},
                        {"stage": "render", "score": 0.0, "grade": "E", "status": "fail", "summary": "render failed"},
                        {"stage": "final_review", "score": 0.0, "grade": "E", "status": "skipped", "summary": "skipped"},
                    ],
                }
            ],
        },
        Path("E:/batch_report.json"),
    )

    assert "- probe: 100.0 (A)" not in content
    assert "- edit_plan: 100.0 (A)" not in content
    assert "- render: 0.0 (E)" in content
    assert "- final_review: 0.0 (E)" in content
    assert "- multi_platform_package:" not in content
    assert "- tts:" not in content
    assert "- ai_effects:" not in content
    assert "- version_scores:" not in content
    assert "  - probe: 100.0 (A) | pass | ok" not in content
    assert "  - render: 0.0 (E) | fail | render failed" in content
    assert "  - final_review: 0.0 (E) | skipped | skipped" in content
