from roughcut.db.models import Artifact, Job, SubtitleItem
from roughcut.pipeline.quality import _build_canonical_transcript_text, _build_subtitle_text, assess_job_quality, collect_editing_risk_gate_signals
from roughcut.review.content_profile import apply_identity_review_guard
from roughcut.review.subtitle_quality import ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT, build_subtitle_quality_report


def _subtitle(index: int, text: str) -> SubtitleItem:
    return SubtitleItem(
        item_index=index,
        start_time=float(index),
        end_time=float(index + 1),
        text_raw=text,
        text_norm=text,
        text_final=text,
    )


def test_visual_only_brand_does_not_override_source_and_transcript_identity() -> None:
    profile = {
        "content_understanding": {"primary_subject": "black plastic device casing"},
        "subject_brand": "DJI",
        "subject_model": "",
        "subject_type": "black plastic device casing",
        "video_theme": "矩阵千机pro机械玩具的多种配置玩法与拆解体验",
        "summary": "博主详述矩阵千机pro玩具的多种配置玩法。",
        "visible_text": "千机pro DJI",
        "visual_hints": {"subject_brand": "DJI", "visible_text": "DJI"},
        "identity_extraction": {
            "resolved": {"subject_brand": "DJI", "subject_model": "", "subject_type": "black plastic device casing"},
            "sources": {"subject_brand": ["visual_cluster"], "subject_model": [], "subject_type": ["visual_cluster"]},
            "candidates": {"subject_brand": [{"value": "DJI", "sources": ["visual_cluster"], "selected": True}]},
        },
    }

    guarded = apply_identity_review_guard(
        profile,
        subtitle_items=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "今天介绍矩阵千机pro这个玩具"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "千机pro有很多DIY配置"},
        ],
        source_name="矩阵 千机pro.MOV",
    )

    assert guarded["subject_brand"] == ""
    assert guarded["visual_hints"]["subject_brand"] == "DJI"
    assert guarded["identity_extraction"]["visual_only_brand_suppressed"]["brand"] == "DJI"
    assert "DJI" not in " ".join(guarded.get("search_queries") or [])


def test_short_hash_named_clip_does_not_fail_on_generic_profile() -> None:
    job = Job(
        source_path="F:/clips/8ab62636b25b4b6ba8398467ddfb371a.mp4",
        source_name="8ab62636b25b4b6ba8398467ddfb371a.mp4",
        status="done",
    )
    profile = {
        "subject_type": "内容待确认",
        "video_theme": "内容待确认",
        "summary": "短素材展示片段",
        "engagement_question": "你怎么看？",
        "automation_review": {"score": 0.6},
    }
    artifact = Artifact(artifact_type="content_profile_final", data_json=profile)

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[artifact],
        subtitle_items=[_subtitle(0, "看一下这里"), _subtitle(1, "这个操作")],
        completion_candidate=True,
    )

    assert assessment["score"] == 100.0
    assert "low_profile_confidence" not in assessment["issue_codes"]
    assert "generic_video_theme" not in assessment["issue_codes"]


def test_informative_source_name_still_requires_specific_profile() -> None:
    job = Job(
        source_path="F:/clips/merged_3_NOC_MT34_S06mini开箱玩法补充_未剪辑.mp4",
        source_name="merged_3_NOC_MT34_S06mini开箱玩法补充_未剪辑.mp4",
        status="done",
    )
    profile = {
        "subject_type": "内容待确认",
        "video_theme": "内容待确认",
        "summary": "短素材展示片段",
        "engagement_question": "你怎么看？",
        "automation_review": {"score": 0.6},
    }
    artifact = Artifact(artifact_type="content_profile_final", data_json=profile)

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[artifact],
        subtitle_items=[_subtitle(0, "看一下这里"), _subtitle(1, "这个操作")],
        completion_candidate=True,
    )

    assert "low_profile_confidence" in assessment["issue_codes"]
    assert assessment["score"] < 100.0


def test_stale_single_word_split_blocker_is_downgraded() -> None:
    job = Job(
        source_path="F:/clips/8ab62636b25b4b6ba8398467ddfb371a.mp4",
        source_name="8ab62636b25b4b6ba8398467ddfb371a.mp4",
        status="done",
    )
    profile = {
        "subject_type": "内容待确认",
        "video_theme": "内容待确认",
        "summary": "短素材展示片段",
        "engagement_question": "你怎么看？",
    }
    artifacts = [
        Artifact(artifact_type="content_profile_final", data_json=profile),
        Artifact(
            artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
            data_json={
                "blocking": True,
                "blocking_reasons": ["普通词跨字幕截断 1 处"],
                "warning_reasons": [],
                "metrics": {"generic_word_split_count": 1},
                "score": 92,
            },
        ),
    ]

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=artifacts,
        subtitle_items=[_subtitle(0, "先介"), _subtitle(1, "绍一下")],
        completion_candidate=True,
    )

    assert "subtitle_quality_blocking" not in assessment["issue_codes"]


def test_quality_assessment_does_not_label_baseline_preserve_warning_as_canonical_projection() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )
    artifacts = [
        Artifact(
            artifact_type="transcript_correction_score_report",
            data_json={
                "score": 79.97,
                "selected_basis": "display_baseline_preserved",
                "selected_transcript_layer": "canonical_transcript",
                "selection_policy": "display_baseline_preserved_for_quality_guard",
            },
        ),
        Artifact(
            artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
            data_json={
                "blocking": False,
                "blocking_reasons": [],
                "warning_reasons": ["普通词跨字幕截断 6 处"],
                "metrics": {"generic_word_split_count": 6},
                "score": 89.86,
            },
        ),
    ]

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=artifacts,
        subtitle_items=[_subtitle(0, "先介绍"), _subtitle(1, "这把刀")],
        completion_candidate=True,
    )

    assert "canonical_projection_quality_warning" not in assessment["issue_codes"]
    assert "subtitle_quality_warning" in assessment["issue_codes"]


def test_quality_assessment_does_not_label_summary_generic_warning_as_canonical_projection() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )
    artifacts = [
        Artifact(
            artifact_type="transcript_correction_score_report",
            data_json={
                "score": 90.86,
                "selected_basis": "canonical_refresh",
                "selected_transcript_layer": "canonical_transcript",
                "selection_policy": "canonical_transcript_is_single_projection_authority",
            },
        ),
        Artifact(
            artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
            data_json={
                "blocking": False,
                "blocking_reasons": [],
                "warning_reasons": ["摘要模板化命中 1 项"],
                "metrics": {
                    "generic_word_split_count": 0,
                    "short_fragment_count": 2,
                    "short_fragment_rate": 0.0063,
                    "semantic_bad_term_total": 0,
                    "summary_generic_hits": ["适合后续做搜索校验、字幕纠错和剪辑包装"],
                },
                "score": 90.86,
            },
        ),
    ]

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=artifacts,
        subtitle_items=[_subtitle(0, "先介绍"), _subtitle(1, "这把刀")],
        completion_candidate=True,
    )

    assert "canonical_projection_quality_warning" not in assessment["issue_codes"]
    assert "subtitle_quality_warning" in assessment["issue_codes"]


def test_segmentation_only_projection_penalty_does_not_trigger_transcript_fidelity_warning() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )
    artifacts = [
        Artifact(
            artifact_type="transcript_correction_score_report",
            data_json={
                "score": 83.57,
                "blocking": False,
                "issue_codes": [],
                "selected_basis": "canonical_refresh",
                "selected_transcript_layer": "canonical_transcript",
                "selection_policy": "canonical_transcript_is_single_projection_authority",
                "candidates": [
                    {
                        "basis": "canonical_refresh",
                        "score": 83.57,
                        "blocking": False,
                        "issue_codes": [],
                        "content_fidelity_score": 100.0,
                        "display_quality_score": 98.86,
                        "segmentation_quality_score": 10.0,
                        "metrics": {
                            "subtitle_count": 316,
                            "fragment_end_count": 4,
                            "fragment_start_count": 4,
                            "short_fragment_count": 2,
                            "generic_word_split_count": 0,
                            "suspicious_boundary_count": 10,
                            "low_confidence_window_count": 61,
                            "missing_material_token_count": 0,
                            "unsupported_material_token_count": 0,
                        },
                    }
                ],
            },
        ),
        Artifact(
            artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
            data_json={
                "blocking": False,
                "blocking_reasons": [],
                "warning_reasons": ["摘要模板化命中 1 项"],
                "metrics": {
                    "generic_word_split_count": 0,
                    "short_fragment_count": 2,
                    "short_fragment_rate": 0.0063,
                    "semantic_bad_term_total": 0,
                    "summary_generic_hits": ["适合后续做搜索校验、字幕纠错和剪辑包装"],
                },
                "score": 90.86,
            },
        ),
    ]

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=artifacts,
        subtitle_items=[_subtitle(0, "先介绍"), _subtitle(1, "这把刀")],
        completion_candidate=True,
    )

    assert "transcript_correction_fidelity_warning" not in assessment["issue_codes"]
    assert "subtitle_quality_warning" in assessment["issue_codes"]


def test_content_fidelity_loss_still_triggers_transcript_fidelity_warning() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )
    artifacts = [
        Artifact(
            artifact_type="transcript_correction_score_report",
            data_json={
                "score": 88.0,
                "blocking": False,
                "issue_codes": ["projection_unsupported_material_tokens"],
                "selected_basis": "canonical_refresh",
                "selected_transcript_layer": "canonical_transcript",
                "selection_policy": "canonical_transcript_is_single_projection_authority",
                "candidates": [
                    {
                        "basis": "canonical_refresh",
                        "score": 88.0,
                        "blocking": False,
                        "issue_codes": ["projection_unsupported_material_tokens"],
                        "content_fidelity_score": 88.0,
                        "display_quality_score": 98.0,
                        "segmentation_quality_score": 98.0,
                        "metrics": {
                            "subtitle_count": 20,
                            "missing_material_token_count": 0,
                            "unsupported_material_token_count": 2,
                            "fragment_start_count": 0,
                            "fragment_end_count": 0,
                            "suspicious_boundary_count": 0,
                            "low_confidence_window_count": 0,
                        },
                    }
                ],
            },
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=artifacts,
        subtitle_items=[_subtitle(0, "先介绍"), _subtitle(1, "这把刀")],
        completion_candidate=True,
    )

    assert "transcript_correction_fidelity_warning" in assessment["issue_codes"]


def test_short_fragment_rate_is_warning_not_blocking() -> None:
    subtitles = [
        {"text_final": "先介"},
        {"text_final": "绍下"},
        {"text_final": "这个"},
        {"text_final": "比较"},
        {"text_final": "还是"},
        {"text_final": "然后"},
        {"text_final": "我们给"},
        {"text_final": "它啊"},
        {"text_final": "啊去"},
        {"text_final": "释放"},
        {"text_final": "挺富"},
        {"text_final": "一点"},
        {"text_final": "换个角度"},
        {"text_final": "再对比一下"},
        {"text_final": "这款手电的按键和光斑表现都比较直观。"},
        {"text_final": "整体内容可以继续进入后续剪辑流程。"},
    ]

    report = build_subtitle_quality_report(subtitle_items=subtitles)

    assert report["blocking"] is False
    assert report["blocking_reasons"] == []
    assert any("短碎句率过高" in reason for reason in report["warning_reasons"])


def test_isolated_complete_short_utterances_do_not_warn_or_penalize() -> None:
    subtitles = [
        {"text_final": "今天主要看这款小包的外观和装载。"},
        {"text_final": "它们都有"},
        {"text_final": "这一段展示正面和背面的做工细节。"},
        {"text_final": "小把手"},
        {"text_final": "你配合这个把手去打开会更顺。"},
        {"text_final": "我们来看"},
        {"text_final": "最后再看肩带和卡扣的使用状态。"},
    ]

    report = build_subtitle_quality_report(subtitle_items=subtitles)

    assert report["blocking"] is False
    assert report["warning_reasons"] == []
    assert report["metrics"]["short_fragment_count"] == 0
    assert report["score"] == 100.0


def test_quality_assessment_applies_source_identity_constraints() -> None:
    job = Job(
        source_path="F:/clips/IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV",
        source_name="IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV",
        status="done",
    )
    profile = {
        "subject_brand": "BOLTBOAT",
        "subject_model": "FXX1小副包",
        "subject_type": "EDC机能包",
        "summary": "BOLTBOAT FXX1小副包挂点与收纳展示",
        "video_theme": "BOLTBOAT FXX1小副包挂点与收纳展示",
        "engagement_question": "你怎么看？",
    }

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[Artifact(artifact_type="content_profile_final", data_json=profile)],
        subtitle_items=[_subtitle(0, "这个影蚀斜挎包"), _subtitle(1, "收纳比较轻量")],
        completion_candidate=True,
    )

    assert "identity_narrative_conflict" not in assessment["issue_codes"]


def test_comparison_target_in_summary_does_not_block_identity_narrative() -> None:
    job = Job(
        source_path="F:/clips/20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        status="done",
    )
    profile = {
        "subject_brand": "NITECORE",
        "subject_model": "EDC17",
        "subject_type": "EDC手电",
        "video_theme": "NITECORE EDC17 与 EDC37 开箱对比",
        "summary": "视频围绕 NITECORE EDC17 开箱展开，并对比 EDC37 的使用差异。",
        "hook_line": "EDC17 和 EDC37 哪个更适合随身携带？",
        "engagement_question": "你更关注哪款手电？",
        "automation_review": {"score": 0.92},
    }

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[Artifact(artifact_type="content_profile_final", data_json=profile)],
        subtitle_items=[
            _subtitle(0, "今天开箱这个EDC17手电"),
            _subtitle(1, "顺便和EDC37做一个对比"),
        ],
        completion_candidate=True,
    )

    assert "identity_narrative_conflict" not in assessment["issue_codes"]


def test_verified_model_alias_in_hook_line_does_not_trigger_identity_narrative_conflict() -> None:
    job = Job(
        source_path="F:/clips/20260212-134637 开箱NOC MT34 也叫S06mini 折刀，还有玩法展示.mp4",
        source_name="20260212-134637 开箱NOC MT34 也叫S06mini 折刀，还有玩法展示.mp4",
        status="done",
    )
    profile = {
        "subject_brand": "NOC",
        "subject_model": "MT34",
        "subject_type": "EDC折刀",
        "subject_domain": "EDC刀具",
        "video_theme": "MT34开箱与功能实测",
        "summary": "这条视频主要围绕NOC MT34展开，内容方向偏产品开箱与上手体验。",
        "hook_line": "一刀难求的NOC S06mini锆合金版开箱",
        "visible_text": "EDC折刀 NOC MT34",
        "identity_review": {
            "evidence_bundle": {
                "candidate_brand": "NOC",
                "candidate_model": "MT34",
                "brand_aliases": ["NOC", "N O C"],
                "model_aliases": [],
                "graph_confirmed_entities": [
                    {
                        "brand": "NOC",
                        "model": "MT34 / S06mini",
                        "phrases": ["NOC MT34 / S06mini", "MT34 / S06mini"],
                        "brand_aliases": [],
                        "model_aliases": [],
                    }
                ],
            }
        },
    }

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[Artifact(artifact_type="content_profile_final", data_json=profile)],
        subtitle_items=[_subtitle(0, "今天开箱这个NOC的小折刀"), _subtitle(1, "它就是MT34也叫S06mini")],
        completion_candidate=True,
    )

    assert "identity_narrative_conflict" not in assessment["issue_codes"]


def test_unverified_model_alias_in_hook_line_still_triggers_identity_narrative_conflict() -> None:
    job = Job(
        source_path="F:/clips/20260212-134637 开箱NOC MT34 也叫S06mini 折刀，还有玩法展示.mp4",
        source_name="20260212-134637 开箱NOC MT34 也叫S06mini 折刀，还有玩法展示.mp4",
        status="done",
    )
    profile = {
        "subject_brand": "NOC",
        "subject_model": "MT34",
        "subject_type": "EDC折刀",
        "video_theme": "MT34开箱与功能实测",
        "summary": "这条视频主要围绕NOC MT34展开，内容方向偏产品开箱与上手体验。",
        "hook_line": "一刀难求的NOC EDC17版开箱",
        "visible_text": "EDC折刀 NOC MT34",
    }

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[Artifact(artifact_type="content_profile_final", data_json=profile)],
        subtitle_items=[_subtitle(0, "今天开箱这个NOC的小折刀"), _subtitle(1, "主体还是MT34")],
        completion_candidate=True,
    )

    assert "identity_narrative_conflict" in assessment["issue_codes"]


def test_build_subtitle_text_respects_display_surface_contract() -> None:
    subtitle = SubtitleItem(
        item_index=0,
        start_time=0.0,
        end_time=1.0,
        text_raw="它算是定位相当高端的一款EC手电了",
        text_norm="它算是定位相当高端的一款EDC手电了",
        text_final="",
    )
    setattr(subtitle, "display_suppressed_reason", "standalone_filler")

    assert _build_subtitle_text([subtitle], canonical_transcript_text="规范转写") == "规范转写"


def test_build_canonical_transcript_text_prefers_explicit_canonical_surface_over_generic_text() -> None:
    assert _build_canonical_transcript_text(
        {
            "segments": [
                {
                    "text": "generic text should not override canonical transcript",
                    "text_raw": "你看到的是EC手电",
                    "text_canonical": "你看到的是EDC手电",
                }
            ]
        }
    ) == "你看到的是EDC手电"


def test_quality_assessment_exposes_refine_decision_summary_signal() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "variants": {"plain": {"segments": []}},
                    "timeline_rules": {
                        "diagnostics": {
                            "refine_decision_summary": {
                                "mode": "auto_refine",
                                "keep_segment_count": 9,
                                "candidate_total": 6,
                                "candidate_auto_apply": 4,
                                "candidate_manual_confirm": 2,
                            }
                        }
                    },
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert assessment["signals"]["refine_decision_summary"] == {
        "mode": "auto_refine",
        "keep_segment_count": 9,
        "candidate_total": 6,
        "candidate_auto_apply": 4,
        "candidate_manual_confirm": 2,
    }


def test_quality_assessment_flags_multimodal_trim_review_timeout() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "variants": {"plain": {"segments": []}},
                    "timeline_rules": {
                        "diagnostics": {
                            "multimodal_trim_review_summary": {
                                "candidate_count": 3,
                                "pending_count": 3,
                                "error": "multimodal_trim_review_timeout",
                            }
                        }
                    },
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert "multimodal_trim_review_timeout" in assessment["issue_codes"]
    assert assessment["signals"]["multimodal_trim_review_summary"] == {
        "candidate_count": 3,
        "pending_count": 3,
        "error": "multimodal_trim_review_timeout",
    }


def test_quality_assessment_blocks_non_monotonic_variant_subtitle_timeline() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "validation": {
                        "status": "warning",
                        "issues": ["packaged: subtitle events are not monotonic at index 14"],
                    },
                    "variants": {"packaged": {"segments": []}},
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert "subtitle_timeline_validation" in assessment["issue_codes"]
    assert any(item["blocking"] for item in assessment["issues"] if item["code"] == "subtitle_timeline_validation")


def test_quality_assessment_flags_unresolved_high_risk_cuts_as_blocking() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "variants": {"plain": {"segments": []}},
                    "timeline_rules": {
                        "diagnostics": {
                            "high_risk_cuts": [
                                {"start": 1.0, "end": 2.0},
                                {"start": 3.0, "end": 4.0},
                            ],
                            "llm_cut_review": {
                                "reviewed": False,
                                "candidate_count": 2,
                            },
                            "multimodal_trim_review_summary": {
                                "candidate_count": 2,
                                "pending_count": 1,
                            },
                            "refine_decision_summary": {
                                "mode": "manual_refine",
                                "candidate_total": 4,
                                "candidate_manual_confirm": 2,
                            },
                        }
                    },
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert "editing_high_risk_cuts_blocking" in assessment["issue_codes"]
    assert assessment["signals"]["high_risk_cut_count"] == 2
    assert any(item["blocking"] for item in assessment["issues"] if item["code"] == "editing_high_risk_cuts_blocking")


def test_quality_assessment_downgrades_high_risk_cut_blocking_when_llm_provider_is_degraded() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "variants": {"plain": {"segments": []}},
                    "timeline_rules": {
                        "diagnostics": {
                            "high_risk_cuts": [
                                {"start": 1.0, "end": 2.0},
                                {"start": 3.0, "end": 4.0},
                            ],
                            "llm_cut_review": {
                                "reviewed": False,
                                "candidate_count": 2,
                                "error": "llm_cut_review_failed",
                            },
                            "multimodal_trim_review_summary": {
                                "candidate_count": 2,
                                "pending_count": 1,
                            },
                            "refine_decision_summary": {
                                "mode": "manual_refine",
                                "candidate_total": 4,
                                "candidate_manual_confirm": 2,
                            },
                        }
                    },
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert "editing_high_risk_cuts_provider_degraded" in assessment["issue_codes"]
    assert "editing_high_risk_cuts_blocking" not in assessment["issue_codes"]
    assert assessment["signals"]["llm_cut_review_provider_degraded"] is True
    assert all(
        not item["blocking"] for item in assessment["issues"] if item["code"] == "editing_high_risk_cuts_provider_degraded"
    )


def test_quality_assessment_does_not_block_advisory_silence_boundary_cuts() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "variants": {"plain": {"segments": []}},
                    "timeline_rules": {
                        "diagnostics": {
                            "high_risk_cuts": [
                                {
                                    "start": 1.0,
                                    "end": 2.0,
                                    "reason": "silence",
                                    "review_priority": "advisory",
                                    "blocking": False,
                                }
                            ],
                            "llm_cut_review": {
                                "reviewed": False,
                                "candidate_count": 1,
                            },
                            "multimodal_trim_review_summary": {
                                "candidate_count": 1,
                                "pending_count": 1,
                            },
                            "refine_decision_summary": {
                                "mode": "manual_refine",
                                "candidate_total": 1,
                                "candidate_manual_confirm": 1,
                            },
                        }
                    },
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert assessment["signals"]["high_risk_cut_count"] == 1
    assert assessment["signals"]["blocking_high_risk_cut_count"] == 0
    assert assessment["signals"]["advisory_high_risk_cut_count"] == 1
    assert assessment["signals"]["blocking_high_risk_cuts"] is False
    assert "editing_high_risk_cuts_blocking" not in assessment["issue_codes"]


def test_quality_assessment_flags_manual_confirm_heavy_edit_plan_as_blocking() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "variants": {"plain": {"segments": []}},
                    "timeline_rules": {
                        "diagnostics": {
                            "high_risk_cuts": [],
                            "llm_cut_review": {
                                "reviewed": True,
                                "candidate_count": 96,
                            },
                            "multimodal_trim_review_summary": {
                                "candidate_count": 96,
                                "pending_count": 1,
                            },
                            "refine_decision_summary": {
                                "mode": "manual_refine",
                                "candidate_total": 96,
                                "candidate_manual_confirm": 96,
                            },
                        }
                    },
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert "editing_manual_confirm_heavy_blocking" in assessment["issue_codes"]
    assert assessment["signals"]["refine_decision_summary"]["candidate_manual_confirm"] == 96
    assert any(
        item["blocking"] for item in assessment["issues"] if item["code"] == "editing_manual_confirm_heavy_blocking"
    )


def test_quality_assessment_does_not_flag_reviewed_unsure_multimodal_as_incomplete() -> None:
    job = Job(
        source_path="F:/clips/demo.mp4",
        source_name="demo.mp4",
        status="done",
    )

    assessment = assess_job_quality(
        job=job,
        steps=[],
        artifacts=[
            Artifact(
                artifact_type="variant_timeline_bundle",
                data_json={
                    "variants": {"plain": {"segments": []}},
                    "timeline_rules": {
                        "diagnostics": {
                            "high_risk_cuts": [],
                            "llm_cut_review": {
                                "reviewed": True,
                                "candidate_count": 1,
                            },
                            "multimodal_trim_review_summary": {
                                "reviewed": True,
                                "candidate_count": 1,
                                "pending_count": 0,
                                "unsure_count": 1,
                            },
                            "refine_decision_summary": {
                                "mode": "auto_refine",
                                "candidate_total": 1,
                                "candidate_manual_confirm": 1,
                            },
                        }
                    },
                },
            )
        ],
        subtitle_items=[_subtitle(0, "演示开场"), _subtitle(1, "继续说明")],
        completion_candidate=True,
    )

    assert "multimodal_trim_review_incomplete" not in assessment["issue_codes"]


def test_collect_editing_risk_gate_signals_matches_quality_blocking_contract() -> None:
    signals = collect_editing_risk_gate_signals(
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
                    "multimodal_trim_review_summary": {
                        "candidate_count": 1,
                        "pending_count": 1,
                    },
                    "refine_decision_summary": {
                        "candidate_manual_confirm": 2,
                    },
                }
            },
        }
    )

    assert signals["high_risk_cut_count"] == 1
    assert signals["llm_cut_review_provider_degraded"] is True
    assert signals["blocking_high_risk_cuts"] is False
    assert signals["blocking_manual_confirm_heavy"] is False
