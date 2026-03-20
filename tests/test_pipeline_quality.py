from __future__ import annotations

import uuid
from datetime import datetime, timezone

from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem
from roughcut.pipeline.quality import assess_job_quality


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        "glossary_review",
        "subtitle_translation",
        "content_profile",
        "ai_director",
        "avatar_commentary",
        "edit_plan",
        "render",
        "final_review",
        "platform_package",
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
