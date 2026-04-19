from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import roughcut.pipeline.quality as quality_mod
import roughcut.pipeline.rerun_actions as rerun_actions_mod
from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem
from roughcut.pipeline.quality import assess_job_quality, evaluate_profile_identity_gate
from roughcut.speech.subtitle_pipeline import ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_transcript_artifact(job: Job, *, text: str = "今天先开箱一下。") -> Artifact:
    return Artifact(
        job_id=job.id,
        artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
        data_json={
            "layer": "canonical_transcript",
            "source_basis": "subtitle_projection_review",
            "segment_count": 1,
            "duration": 3.0,
            "correction_metrics": {
                "accepted_correction_count": 0,
                "pending_correction_count": 0,
            },
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 3.0,
                    "text": text,
                    "text_raw": text,
                    "text_canonical": text,
                    "source_subtitle_index": 0,
                    "accepted_corrections": [],
                    "pending_corrections": [],
                    "words": [],
                }
            ],
        },
        created_at=_now(),
    )


def test_rerun_actions_resolve_shared_issue_mapping_and_chain():
    assert rerun_actions_mod.rerun_start_step_for_issue("subtitle_quality_warning") == "subtitle_postprocess"
    assert rerun_actions_mod.rerun_steps_for_issue_code("subtitle_quality_warning") == [
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ]
    assert rerun_actions_mod.rerun_start_step_for_issue("missing_canonical_transcript_layer") == "transcript_review"
    assert rerun_actions_mod.rerun_steps_for_issue_code("missing_canonical_transcript_layer") == [
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ]


def test_pick_recommended_rerun_steps_prefers_shared_override_over_auto_fix_step():
    issues = [
        quality_mod.QualityIssue(
            code="subtitle_quality_warning",
            message="字幕质量存在警告",
            penalty=6.0,
            auto_fix_step="render",
        ),
        quality_mod.QualityIssue(
            code="missing_content_profile",
            message="缺少内容画像结果",
            penalty=30.0,
            auto_fix_step="content_profile",
        ),
    ]

    assert rerun_actions_mod.pick_recommended_rerun_steps(issues) == [
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ]


def test_pick_recommended_rerun_steps_returns_empty_for_manual_review_only_issue():
    issues = [
        quality_mod.QualityIssue(
            code="subtitle_semantic_contamination",
            message="检测到语义污染 4 处，必须人工确认",
            penalty=16.0,
            blocking=True,
        )
    ]

    assert rerun_actions_mod.pick_recommended_rerun_steps(issues) == []


def test_assess_job_quality_treats_identity_missing_quality_signal_as_warning():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/identity-warning.mp4",
        source_name="identity-warning.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done")]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="subtitle_quality_report",
            data_json={
                "score": 88.0,
                "blocking": False,
                "blocking_reasons": [],
                "warning_reasons": ["摘要/主体未保住文件名中的品牌型号"],
                "metrics": {"identity_missing": True},
            },
            created_at=_now(),
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=[
            SubtitleItem(
                job_id=job.id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="测试字幕",
            )
        ],
        corrections=[],
    )

    assert "subtitle_quality_warning" in assessment["issue_codes"]
    assert "subtitle_identity_missing" not in assessment["issue_codes"]


def test_assess_job_quality_penalizes_generic_profile_and_missed_detail():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/detail.mp4",
        source_name="detail.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
        JobStep(job_id=job.id, step_name="render", status="done"),
        JobStep(job_id=job.id, step_name="platform_package", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_type": "开箱产品",
                "video_theme": "开箱评测",
                "summary": "围绕开箱产品展开，偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
                "engagement_question": "你觉得值不值？",
                "preset_name": "edc_tactical",
                "automation_review": {"score": 0.61},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job),
        Artifact(
            job_id=job.id,
            artifact_type="render_outputs",
            data_json={
                "packaged_mp4": "E:/tmp/detail.mp4",
                "plain_mp4": "E:/tmp/detail_plain.mp4",
                "ai_effect_mp4": "E:/tmp/detail_fx.mp4",
                "avatar_result": {"status": "done", "detail": "数字人已写回"},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job, text="Loop露普SK05二代UV版和一代做对比。"),
        Artifact(
            job_id=job.id,
            artifact_type="platform_packaging_md",
            storage_path="E:/tmp/detail_publish.md",
            created_at=_now(),
        ),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="Loop露普SK05二代UV版和一代做对比，亮度提升1000lm，续航三小时。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert assessment["grade"] in {"C", "D"}
    assert assessment["score"] < 75.0
    assert "generic_summary" in assessment["issue_codes"]
    assert "detail_blind" in assessment["issue_codes"]
    assert "comparison_blind" in assessment["issue_codes"]
    assert assessment["recommended_rerun_step"] == "content_profile"
    assert assessment["recommended_rerun_steps"] == [
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ]


def test_assess_job_quality_prefers_subtitle_rerun_when_subtitles_missing():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/subtitles.mp4",
        source_name="subtitles.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
        JobStep(job_id=job.id, step_name="glossary_review", status="done"),
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "Loop露普",
                "subject_model": "SK05二代UV版",
                "subject_type": "EDC手电",
                "video_theme": "SK05二代UV版与一代亮度续航对比",
                "summary": "围绕 Loop露普 SK05二代UV版 和一代做亮度、续航与 UV 功能差异对比。",
                "engagement_question": "你更在意二代的 UV 功能还是亮度升级？",
                "preset_name": "edc_tactical",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.92},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job),
    ]
    corrections = [
        SubtitleCorrection(
            job_id=job.id,
            original_span="uv",
            suggested_span="UV",
            change_type="term",
            confidence=0.95,
            human_decision=None,
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=[],
        corrections=corrections,
        completion_candidate=True,
    )

    assert "missing_subtitles" in assessment["issue_codes"]
    assert assessment["recommended_rerun_step"] == "subtitle_postprocess"
    assert assessment["recommended_rerun_steps"] == [
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
    ]


@pytest.mark.parametrize("completed_step", ["transcript_review", "content_profile"])
def test_assess_job_quality_flags_missing_canonical_transcript_layer_after_review_steps(completed_step):
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/canonical-missing.mp4",
        source_name="canonical-missing.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [JobStep(job_id=job.id, step_name=completed_step, status="done")]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "Loop露普",
                "subject_model": "SK05二代UV版",
                "subject_type": "EDC手电",
                "video_theme": "SK05二代UV版开箱与对比",
                "summary": "这条视频聚焦 Loop露普 SK05二代UV版 的对比表现与亮度升级。",
                "engagement_question": "你更看重对比还是亮度？",
                "preset_name": "edc_tactical",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.93},
            },
            created_at=_now(),
        ),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=3.0,
            text_raw="今天先开箱一下。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert "missing_canonical_transcript_layer" in assessment["issue_codes"]
    issue = next(item for item in assessment["issues"] if item["code"] == "missing_canonical_transcript_layer")
    assert issue["blocking"] is True
    assert issue["auto_fix_step"] == "transcript_review"
    assert assessment["recommended_rerun_step"] == "transcript_review"
    assert assessment["recommended_rerun_steps"][:3] == [
        "transcript_review",
        "subtitle_translation",
        "content_profile",
    ]
    assert assessment["signals"]["transcript_context"]["source"] == "subtitle_items"
    assert assessment["signals"]["transcript_context"]["canonical_transcript_layer_present"] is False


def test_assess_job_quality_uses_subtitle_stage_reports_for_rerun_paths():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/subtitle-stage.mp4",
        source_name="subtitle-stage.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
        JobStep(job_id=job.id, step_name="subtitle_term_resolution", status="done"),
        JobStep(job_id=job.id, step_name="subtitle_consistency_review", status="done"),
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "Loop露普",
                "subject_model": "SK05二代UV版",
                "subject_type": "EDC手电",
                "video_theme": "SK05二代UV版与一代亮度续航对比",
                "summary": "围绕 Loop露普 SK05二代UV版 和一代做亮度、续航与 UV 功能差异对比。",
                "engagement_question": "你更在意二代的 UV 功能还是亮度升级？",
                "preset_name": "edc_tactical",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.95},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job),
        Artifact(
            job_id=job.id,
            artifact_type="subtitle_quality_report",
            data_json={
                "score": 61.5,
                "blocking": True,
                "blocking_reasons": ["热词/型号错词残留 2 处"],
                "warning_reasons": ["独立语气词偏多 1.2%"],
                "metrics": {"identity_missing": False},
            },
            created_at=_now(),
        ),
        Artifact(
            job_id=job.id,
            artifact_type="subtitle_term_resolution_patch",
            data_json={
                "metrics": {
                    "patch_count": 3,
                    "pending_count": 2,
                    "auto_applied_count": 1,
                }
            },
            created_at=_now(),
        ),
        Artifact(
            job_id=job.id,
            artifact_type="subtitle_consistency_report",
            data_json={
                "score": 87.0,
                "blocking": False,
                "blocking_reasons": [],
                "warning_reasons": ["字幕术语已自动纠偏 1 处"],
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job, text="这期重点看手电 UV 版和一代亮度差异。"),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="这次重点看二代 UV 版和一代在亮度和续航上的区别。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert assessment["issue_codes"] == [
        "subtitle_terms_pending",
        "subtitle_consistency_warning",
        "subtitle_quality_blocking",
    ]
    assert assessment["recommended_rerun_step"] == "subtitle_postprocess"
    assert assessment["recommended_rerun_steps"][:3] == [
        "subtitle_postprocess",
        "subtitle_term_resolution",
        "subtitle_consistency_review",
    ]


def test_assess_job_quality_penalizes_subtitle_sync_issue_and_prefers_render_rerun():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/sync.mp4",
        source_name="sync.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
        JobStep(job_id=job.id, step_name="glossary_review", status="done"),
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
        JobStep(job_id=job.id, step_name="render", status="done"),
        JobStep(job_id=job.id, step_name="platform_package", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "Loop露普",
                "subject_model": "SK05二代UV版",
                "subject_type": "EDC手电",
                "video_theme": "SK05二代UV版与一代亮度续航对比",
                "summary": "围绕 Loop露普 SK05二代UV版 和一代做亮度、续航与 UV 功能差异对比。",
                "engagement_question": "你更在意二代的 UV 功能还是亮度升级？",
                "preset_name": "edc_tactical",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.95},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job),
        Artifact(
            job_id=job.id,
            artifact_type="render_outputs",
            data_json={
                "packaged_mp4": "E:/tmp/sync.mp4",
                "packaged_srt": "E:/tmp/sync.srt",
                "quality_checks": {
                    "subtitle_sync": {
                        "status": "warning",
                        "message": "成片字幕存在越界或明显首尾错位",
                        "warning_codes": ["subtitle_out_of_bounds", "subtitle_duration_gap_large"],
                    }
                },
            },
            created_at=_now(),
        ),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="这次重点看二代 UV 版和一代在亮度和续航上的区别。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert "subtitle_sync_issue" in assessment["issue_codes"]
    assert assessment["recommended_rerun_step"] == "render"
    assert assessment["recommended_rerun_steps"] == ["render", "final_review", "platform_package"]


def test_assess_job_quality_marks_semantic_contamination_as_manual_review_only():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/semantic-contamination.mp4",
        source_name="semantic-contamination.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "奈特科尔",
                "subject_model": "EDC17",
                "subject_type": "EDC手电",
                "video_theme": "奈特科尔 EDC17 开箱与 EDC37 对比",
                "summary": "这条视频围绕奈特科尔 EDC17 手电的开箱与对比展开。",
                "engagement_question": "你更偏向 EDC17 还是 EDC37？",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.94},
            },
            created_at=_now(),
        ),
        Artifact(
            job_id=job.id,
            artifact_type="subtitle_quality_report",
            data_json={
                "score": 52.0,
                "blocking": True,
                "blocking_reasons": ["检测到语义污染 4 处，必须人工确认"],
                "warning_reasons": [],
                "metrics": {
                    "semantic_bad_term_total": 4,
                    "lexical_bad_term_total": 1,
                },
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job, text="这期重点看 EDC17 和 EDC37 的便携差异。"),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=3.0,
            text_raw="这期重点看 EDC17 和 EDC37 的便携差异。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert assessment["issue_codes"] == ["subtitle_semantic_contamination"]
    assert assessment["recommended_rerun_step"] is None
    assert assessment["recommended_rerun_steps"] == []
    assert assessment["auto_fixable"] is False


def test_assess_job_quality_reports_canonical_transcript_context_when_present():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/canonical-context.mp4",
        source_name="canonical-context.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "Loop露普",
                "subject_model": "SK05二代UV版",
                "subject_type": "EDC手电",
                "video_theme": "SK05二代UV版开箱与对比",
                "summary": "这条视频聚焦 Loop露普 SK05二代UV版 的对比表现与亮度升级。",
                "engagement_question": "你更看重对比还是亮度？",
                "preset_name": "edc_tactical",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.93},
            },
            created_at=_now(),
        ),
        Artifact(
            job_id=job.id,
            artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
            data_json={
                "layer": "canonical_transcript",
                "source_basis": "subtitle_projection_review",
                "segment_count": 1,
                "duration": 3.0,
                "correction_metrics": {
                    "accepted_correction_count": 1,
                    "pending_correction_count": 0,
                },
                "segments": [
                    {
                        "index": 0,
                        "start": 0.0,
                        "end": 3.0,
                        "text": "今天对比二代和一代的亮度升级。",
                        "text_raw": "今天先开箱一下。",
                        "text_canonical": "今天对比二代和一代的亮度升级。",
                        "source_subtitle_index": 0,
                        "accepted_corrections": [],
                        "pending_corrections": [],
                        "words": [],
                    }
                ],
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job, text="这期重点看手电 UV 版和一代亮度差异。"),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=3.0,
            text_raw="今天先开箱一下。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert assessment["signals"]["transcript_context"]["source"] == "canonical_transcript_layer"
    assert assessment["signals"]["transcript_context"]["canonical_transcript_layer_present"] is True
    assert assessment["signals"]["transcript_context"]["canonical_transcript_layer_segment_count"] == 1
    assert assessment["signals"]["transcript_context"]["canonical_transcript_layer_source_basis"] == "subtitle_projection_review"


def test_assess_job_quality_surfaces_edit_plan_llm_cut_review_timeout():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/edit_plan_timeout.mp4",
        source_name="edit_plan_timeout.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
        JobStep(job_id=job.id, step_name="edit_plan", status="done"),
        JobStep(job_id=job.id, step_name="render", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "FOXBAT狐蝠工业",
                "subject_model": "FXX1小副包",
                "subject_type": "EDC机能包",
                "video_theme": "FOXBAT狐蝠工业FXX1小副包开箱与分仓挂点评测",
                "summary": "这条视频主要围绕 FOXBAT狐蝠工业 FXX1小副包 的分仓和挂点展开。",
                "engagement_question": "你更在意分仓还是挂点？",
                "preset_name": "edc_tactical",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.95},
            },
            created_at=_now(),
        ),
        Artifact(
            job_id=job.id,
            artifact_type="variant_timeline_bundle",
            data_json={
                "variants": {},
                "timeline_rules": {
                    "diagnostics": {
                        "llm_cut_review": {
                            "reviewed": False,
                            "candidate_count": 2,
                            "error": "llm_cut_review_timeout",
                            "timeout": True,
                        }
                    }
                }
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="今天开箱狐蝠工业 F21 小副包，重点看分仓和挂点。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert "edit_plan_llm_cut_review_timeout" in assessment["issue_codes"]
    assert "edit_plan" in assessment["recommended_rerun_steps"]
    assert assessment["signals"]["llm_cut_review"]["timeout"] is True


def test_assess_job_quality_uses_content_understanding_detail_evidence_for_coverage():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/mt34.mp4",
        source_name="mt34.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "NOC",
                "subject_model": "MT34",
                "subject_type": "NOC MT34 EDC折刀",
                "video_theme": "MT34开箱与功能实测",
                "summary": "这条视频主要围绕NOC MT34展开，内容方向偏产品开箱与上手体验。",
                "engagement_question": "你更喜欢哪种快开方式？",
                "content_understanding": {
                    "summary": "UP主补充演示NOC MT34快开组件可拆卸的DIY玩法，体验按压、抠、拧三种快开方式的手感差异。",
                    "video_theme": "NOC MT34快开组件可拆卸DIY实测与手感体验",
                    "semantic_facts": {
                        "aspect_candidates": ["DIY可玩性", "拆卸便捷性", "手感", "重量"],
                        "component_candidates": ["快开组件", "前置组件"],
                    },
                    "evidence_spans": [
                        {"text": "三个快开方式都是可以拆的"},
                        {"text": "它是一个独立的件儿它是可以完全可以拧开"},
                        {"text": "一个很好的手感和反馈然后加上它一个合适的重量"},
                    ],
                },
            },
            created_at=_now(),
        ),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="三个快开方式都是可以拆的，而且有很好的手感和反馈，加上它一个合适的重量。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert "detail_blind" not in assessment["issue_codes"]


def test_assess_job_quality_ignores_conflicting_identity_detail_cues():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/mt34-conflict.mp4",
        source_name="mt34-conflict.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "NOC",
                "subject_model": "MT34",
                "subject_type": "NOC MT34 EDC折刀",
                "video_theme": "NOC MT34手感讲解",
                "summary": "这条视频主要围绕NOC MT34展开，重点提到快开方式、DIY改法和前快开结构，内容方向偏产品讲解，适合后续做信息核对。",
                "engagement_question": "你更在意哪一种快开手感？",
                "content_understanding": {
                    "summary": "视频演示NOC MT34与EDC17别名相关的多种快开方式、DIY改法和前快开结构。",
                    "semantic_facts": {
                        "aspect_candidates": ["DIY改法"],
                        "component_candidates": ["快开方式", "前快开结构", "EDC17折刀帕"],
                    },
                },
            },
            created_at=_now(),
        ),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="这个EDC17折刀帕其实是在讲MT34的快开方式、前快开结构和DIY改法。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert "detail_blind" not in assessment["issue_codes"]


def test_compute_subtitle_sync_check_allows_expected_outro_gap(monkeypatch, tmp_path):
    video_path = tmp_path / "packaged.mp4"
    srt_path = tmp_path / "packaged.srt"
    video_path.write_text("placeholder", encoding="utf-8")
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\n测试\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(quality_mod, "_probe_media_duration", lambda path: 13.0)
    monkeypatch.setattr(
        quality_mod,
        "_probe_media_stream_durations",
        lambda path: {"video_duration_sec": 13.0, "audio_duration_sec": 13.0},
    )

    result = quality_mod._compute_subtitle_sync_check(
        video_path,
        srt_path,
        allowed_trailing_gap_sec=3.1,
    )

    assert result is not None
    assert result["status"] == "ok"
    assert result["effective_trailing_gap_sec"] == pytest.approx(0.0)


def test_compute_subtitle_sync_check_flags_audio_video_duration_gap(monkeypatch, tmp_path):
    video_path = tmp_path / "packaged.mp4"
    srt_path = tmp_path / "packaged.srt"
    video_path.write_text("placeholder", encoding="utf-8")
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:10,000\n测试\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(quality_mod, "_probe_media_duration", lambda path: 10.0)
    monkeypatch.setattr(
        quality_mod,
        "_probe_media_stream_durations",
        lambda path: {"video_duration_sec": 20.0, "audio_duration_sec": 10.0},
    )

    result = quality_mod._compute_subtitle_sync_check(video_path, srt_path)

    assert result is not None
    assert result["status"] == "warning"
    assert "audio_video_duration_gap_large" in result["warning_codes"]
    assert result["audio_video_duration_gap_sec"] == pytest.approx(10.0)


def test_compute_subtitle_sync_check_flags_timestamp_disorder_and_overlap(monkeypatch, tmp_path):
    video_path = tmp_path / "packaged.mp4"
    srt_path = tmp_path / "packaged.srt"
    video_path.write_text("placeholder", encoding="utf-8")
    srt_path.write_text(
        "\n".join(
            [
                "1",
                "00:00:04,000 --> 00:00:05,000",
                "后面",
                "",
                "2",
                "00:00:02,500 --> 00:00:04,500",
                "前面但重叠",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(quality_mod, "_probe_media_duration", lambda path: 10.0)
    monkeypatch.setattr(
        quality_mod,
        "_probe_media_stream_durations",
        lambda path: {"video_duration_sec": 10.0, "audio_duration_sec": 10.0},
    )

    result = quality_mod._compute_subtitle_sync_check(video_path, srt_path)

    assert result is not None
    assert result["status"] == "warning"
    assert "subtitle_timestamp_disorder" in result["warning_codes"]
    assert "subtitle_overlap_detected" in result["warning_codes"]
    assert result["subtitle_timestamp_disorder_count"] == 1
    assert result["subtitle_overlap_count"] == 1


def test_assess_job_quality_prefers_variant_bundle_packaged_quality_checks():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/bundle.mp4",
        source_name="bundle.mp4",
        status="done",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
        JobStep(job_id=job.id, step_name="glossary_review", status="done"),
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
        JobStep(job_id=job.id, step_name="render", status="done"),
        JobStep(job_id=job.id, step_name="platform_package", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "Loop露普",
                "subject_model": "SK05二代UV版",
                "subject_type": "EDC手电",
                "video_theme": "SK05二代UV版与一代亮度续航对比",
                "summary": "围绕 Loop露普 SK05二代UV版 和一代做亮度、续航与 UV 功能差异对比。",
                "engagement_question": "你更在意二代的 UV 功能还是亮度升级？",
                "preset_name": "edc_tactical",
                "review_mode": "auto_confirmed",
                "automation_review": {"score": 0.95},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job),
        Artifact(
            job_id=job.id,
            artifact_type="render_outputs",
            data_json={
                "packaged_mp4": "E:/tmp/bundle.mp4",
                "packaged_srt": "E:/tmp/bundle.srt",
                "quality_checks": {
                    "subtitle_sync": {
                        "status": "ok",
                        "message": "render outputs remain aligned",
                        "warning_codes": [],
                    }
                },
            },
            created_at=_now(),
        ),
        Artifact(
            job_id=job.id,
            artifact_type="variant_timeline_bundle",
            data_json={
                "timeline_rules": {"lead_in_sec": 1.5},
                "variants": {
                    "packaged": {
                        "media": {"path": "E:/tmp/bundle.mp4"},
                        "subtitle_events": [
                            {"start_time": 0.0, "end_time": 2.4, "text": "bundle subtitle one"},
                            {"start_time": 2.8, "end_time": 6.2, "text": "bundle subtitle two"},
                        ],
                        "overlay_events": [],
                        "quality_checks": {
                            "subtitle_sync": {
                                "status": "warning",
                                "message": "bundle packaged timing is off",
                                "warning_codes": ["subtitle_out_of_bounds"],
                            }
                        },
                    }
                },
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job, text="这期重点看手电 UV 版和一代亮度差异。"),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="这次重点看二代 UV 版和一代在亮度和续航上的区别。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=True,
    )

    assert assessment["issue_codes"] == ["subtitle_sync_issue"]
    assert assessment["signals"]["subtitle_sync"]["status"] == "warning"
    assert assessment["signals"]["subtitle_sync"]["message"] == "bundle packaged timing is off"


def test_assess_job_quality_blocks_subject_conflict_between_subtitles_and_profile():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/luckykiss.mp4",
        source_name="luckykiss.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_type": "多功能工具钳",
                "video_theme": "工具钳开箱",
                "summary": "这条视频主要围绕多功能工具钳展开。",
                "engagement_question": "这类工具钳你会随身带吗？",
                "preset_name": "edc_tactical",
                "review_mode": "manual_confirmed",
                "automation_review": {"score": 0.91},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job, text="今天给大家说一下 LuckyKiss 的 KissPod。"),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=4.0,
            text_raw="今天给大家介绍一个 LuckyKiss 的益生菌含片，产品名叫 KissPod。",
        ),
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=1,
            start_time=4.0,
            end_time=8.0,
            text_raw="这个含片主打口气清新和零糖，还是弹射入口的玩法。",
        ),
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=False,
    )

    assert "subject_conflict" in assessment["issue_codes"]
    assert assessment["auto_fixable"] is False
    assert assessment["recommended_rerun_step"] == "content_profile"


def test_assess_job_quality_blocks_identity_narrative_conflict_inside_profile():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/arc.mp4",
        source_name="arc.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "LuckyKiss",
                "subject_model": "KissPod",
                "subject_type": "LuckyKiss KissPod 益生菌含片",
                "video_theme": "LEATHERMAN ARC 多功能工具钳开箱",
                "summary": "这条视频主要围绕 LEATHERMAN ARC 多功能钳展开，补充上手体验和结构细节。",
                "hook_line": "ARC 到底值不值",
                "engagement_question": "你会买 ARC 吗？",
                "preset_name": "edc_tactical",
                "review_mode": "manual_confirmed",
                "automation_review": {"score": 0.95},
            },
            created_at=_now(),
        ),
        _canonical_transcript_artifact(job, text="今天给大家说一下 LuckyKiss 和 KissPod。"),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=3.0,
            text_raw="今天给大家介绍 LuckyKiss 的 KissPod 益生菌含片，主打弹射入口和口气清新。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=False,
    )

    assert "identity_narrative_conflict" in assessment["issue_codes"]
    assert assessment["auto_fixable"] is False
    assert assessment["recommended_rerun_step"] == "content_profile"
    assert "summary" in assessment["signals"]["identity_narrative_conflicts"]


def test_assess_job_quality_blocks_entity_catalog_conflict_from_verification_evidence():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/fxx1.mp4",
        source_name="fxx1.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "LEATHERMAN",
                "subject_model": "ARC",
                "subject_type": "多功能工具钳",
                "video_theme": "工具钳开箱",
                "summary": "这条视频主要围绕工具钳展开。",
                "verification_evidence": {
                    "entity_catalog_candidates": [
                        {
                            "brand": "狐蝠工业",
                            "model": "FXX1小副包",
                            "primary_subject": "狐蝠工业 FXX1小副包",
                            "matched_fields": ["video_evidence", "brand_alias", "model_alias"],
                            "matched_evidence_texts": ["这期鸿福 F叉二一小副包做个开箱测评。"],
                            "evidence_strength": "strong",
                            "support_score": 0.86,
                            "confidence": 0.9,
                        }
                    ]
                },
            },
            created_at=_now(),
        ),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=2.0,
            text_raw="这期鸿福 F叉二一小副包做个开箱测评。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=False,
    )

    assert "entity_catalog_conflict" in assessment["issue_codes"]
    assert assessment["signals"]["entity_identity_gate"]["blocking"] is True
    assert assessment["signals"]["entity_identity_gate"]["conflicts"] == ["subject_brand", "subject_model"]


def test_evaluate_profile_identity_gate_marks_missing_fields_when_catalog_has_strong_candidate():
    gate = evaluate_profile_identity_gate(
        {
            "subject_brand": "",
            "subject_model": "",
            "verification_evidence": {
                "entity_catalog_candidates": [
                    {
                        "brand": "狐蝠工业",
                        "model": "FXX1小副包",
                        "primary_subject": "狐蝠工业 FXX1小副包",
                        "matched_fields": ["video_evidence", "brand_alias"],
                        "matched_evidence_texts": ["这期鸿福 F叉二一小副包做个开箱测评。"],
                        "evidence_strength": "strong",
                        "support_score": 0.81,
                        "confidence": 0.86,
                    }
                ]
            },
        }
    )

    assert gate["needs_review"] is True
    assert gate["blocking"] is False
    assert gate["missing_supported_fields"] == ["subject_brand", "subject_model"]


def test_evaluate_profile_identity_gate_ignores_moderate_low_support_catalog_candidate():
    gate = evaluate_profile_identity_gate(
        {
            "subject_brand": "天敌",
            "subject_model": "天敌",
            "verification_evidence": {
                "entity_catalog_candidates": [
                    {
                        "brand": "NOC",
                        "model": "",
                        "primary_subject": "NOC",
                        "matched_fields": ["video_evidence", "brand_alias"],
                        "matched_evidence_texts": ["没想到这 NOC 现在这么火。"],
                        "evidence_strength": "moderate",
                        "support_score": 0.56,
                        "confidence": 0.56,
                    }
                ]
            },
        }
    )

    assert gate["blocking"] is False
    assert gate["conflicts"] == []
    assert gate["missing_supported_fields"] == []


def test_evaluate_profile_identity_gate_blocks_narrative_conflict_from_catalog_candidate():
    gate = evaluate_profile_identity_gate(
        {
            "subject_brand": "",
            "subject_model": "FXX1小副包",
            "subject_type": "LEATHERMAN FXX1小副包",
            "summary": "这条视频主要围绕 FXX1小副包 展开。",
            "verification_evidence": {
                "entity_catalog_candidates": [
                    {
                        "brand": "狐蝠工业",
                        "model": "FXX1小副包",
                        "primary_subject": "狐蝠工业 FXX1小副包",
                        "matched_fields": ["video_evidence", "brand_alias", "model_alias", "supporting_keyword"],
                        "matched_evidence_texts": ["这期鸿福 F叉二一小副包做个开箱测评，重点看分仓和挂点。"],
                        "matched_aliases": {"brand": ["鸿福"], "model": ["F叉二一小副包"]},
                        "evidence_strength": "strong",
                        "support_score": 0.89,
                        "confidence": 0.93,
                    }
                ]
            },
        }
    )

    assert gate["needs_review"] is True
    assert gate["blocking"] is True
    assert gate["narrative_conflicts"] == ["subject_type"]


def test_evaluate_profile_identity_gate_treats_model_family_variant_as_compatible():
    gate = evaluate_profile_identity_gate(
        {
            "subject_brand": "",
            "subject_model": "FXX1",
            "subject_type": "狐蝠工业 FXX1小副包",
            "verification_evidence": {
                "entity_catalog_candidates": [
                    {
                        "brand": "狐蝠工业",
                        "model": "FXX1小副包",
                        "primary_subject": "狐蝠工业 FXX1小副包",
                        "matched_fields": ["video_evidence", "brand_alias", "model_alias", "supporting_keyword"],
                        "matched_evidence_texts": ["这期鸿福 F叉二一小副包做个开箱测评，重点看分仓和挂点。"],
                        "matched_aliases": {"brand": ["鸿福"], "model": ["F叉二一小副包"]},
                        "evidence_strength": "strong",
                        "support_score": 0.89,
                        "confidence": 0.93,
                    }
                ]
            },
        }
    )

    assert gate["conflicts"] == []
    assert gate["missing_supported_fields"] == ["subject_brand"]


def test_evaluate_profile_identity_gate_prefers_model_aligned_candidate_over_glossary_noise():
    gate = evaluate_profile_identity_gate(
        {
            "subject_brand": "",
            "subject_model": "FXX1小副包",
            "subject_type": "狐蝠工业FXX1小副包",
            "verification_evidence": {
                "entity_catalog_candidates": [
                    {
                        "brand": "LEATHERMAN",
                        "model": "FXX1",
                        "primary_subject": "LEATHERMAN FXX1",
                        "matched_fields": ["glossary_alias", "search_queries", "video_evidence"],
                        "matched_evidence_texts": ["这期鸿福 FXX1 小副包做个开箱测评。"],
                        "matched_aliases": {"brand": ["LEATHERMAN"], "model": ["FXX1"]},
                        "evidence_strength": "moderate",
                        "support_score": 0.76,
                        "confidence": 0.8,
                        "subject_domain": "edc",
                    },
                    {
                        "brand": "狐蝠工业",
                        "model": "FXX1",
                        "primary_subject": "狐蝠工业 FXX1",
                        "matched_fields": ["glossary_alias", "brand_alias", "model_alias", "video_evidence", "supporting_keyword"],
                        "matched_evidence_texts": ["这期鸿福 FXX1 小副包做个开箱测评。"],
                        "matched_aliases": {"brand": ["鸿福"], "model": ["FXX1"]},
                        "evidence_strength": "moderate",
                        "support_score": 0.76,
                        "confidence": 0.8,
                        "subject_domain": "bag",
                        "subject_type": "机能副包",
                    },
                ]
            },
        }
    )

    assert gate["top_candidate"]["brand"] == "狐蝠工业"
    assert gate["missing_supported_fields"] == ["subject_brand"]
    assert gate["narrative_conflicts"] == []


def test_assess_job_quality_blocks_entity_catalog_narrative_conflict():
    job = Job(
        id=uuid.uuid4(),
        source_path="jobs/demo/fxx1.mp4",
        source_name="fxx1.mp4",
        status="processing",
        language="zh-CN",
    )
    steps = [
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
    ]
    artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="content_profile_final",
            data_json={
                "subject_brand": "",
                "subject_model": "FXX1小副包",
                "subject_type": "LEATHERMAN FXX1小副包",
                "video_theme": "FXX1小副包开箱",
                "summary": "这条视频主要围绕 FXX1小副包 展开。",
                "verification_evidence": {
                    "entity_catalog_candidates": [
                        {
                            "brand": "狐蝠工业",
                            "model": "FXX1小副包",
                            "primary_subject": "狐蝠工业 FXX1小副包",
                            "matched_fields": ["video_evidence", "brand_alias", "model_alias", "supporting_keyword"],
                            "matched_evidence_texts": ["这期鸿福 F叉二一小副包做个开箱测评。"],
                            "matched_aliases": {"brand": ["鸿福"], "model": ["F叉二一小副包"]},
                            "evidence_strength": "strong",
                            "support_score": 0.89,
                            "confidence": 0.93,
                        }
                    ]
                },
            },
            created_at=_now(),
        ),
    ]
    subtitles = [
        SubtitleItem(
            job_id=job.id,
            version=1,
            item_index=0,
            start_time=0.0,
            end_time=2.0,
            text_raw="这期鸿福 F叉二一小副包做个开箱测评。",
        )
    ]

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=[],
        completion_candidate=False,
    )

    assert "entity_catalog_narrative_conflict" in assessment["issue_codes"]
    assert assessment["signals"]["entity_identity_gate"]["blocking"] is True
    assert assessment["signals"]["entity_identity_gate"]["narrative_conflicts"] == ["subject_type"]
