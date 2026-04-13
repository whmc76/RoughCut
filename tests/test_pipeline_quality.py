from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import roughcut.pipeline.quality as quality_mod
from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem
from roughcut.pipeline.quality import assess_job_quality, evaluate_profile_identity_gate


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
