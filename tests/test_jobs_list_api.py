from __future__ import annotations

import uuid

import pytest

from roughcut.db.models import Artifact, Job, JobStep


@pytest.mark.asyncio
async def test_jobs_list_returns_preview_fields_with_filtered_artifacts(client, db_session):
    job_id = uuid.uuid4()
    db_session.add(
        Job(
            id=job_id,
            source_path="jobs/demo/list-preview.mp4",
            source_name="list-preview.mp4",
            status="needs_review",
            language="zh-CN",
            workflow_template="edc_tactical",
            workflow_mode="standard_edit",
            enhancement_modes=["avatar_commentary", "auto_review"],
        )
    )
    db_session.add_all(
        [
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="done",
                metadata_={"source_context": {"merged_source_names": ["part-a.mp4", "part-b.mp4"]}},
            ),
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="pending",
                metadata_={"detail": "等待人工核对。"},
            ),
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2 Ultra",
                    "video_theme": "户外照明",
                    "summary": "这是任务列表需要显示的摘要。",
                    "automation_review": {
                        "blocking_reasons": ["首次出现新型号，需要人工确认。"],
                    },
                },
            ),
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "score": 88.0,
                    "grade": "B",
                    "issue_codes": ["generic_video_theme"],
                },
            ),
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "avatar_result": {
                        "status": "done",
                        "detail": "数字人口播已写入成片",
                    }
                },
            ),
            Artifact(
                job_id=job_id,
                artifact_type="transcript_evidence",
                data_json={
                    "raw_segments": [
                        {"text": "this is intentionally irrelevant to list previews"},
                    ]
                },
            ),
        ]
    )
    await db_session.commit()

    response = await client.get("/api/v1/jobs?limit=1")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["source_name"] == "list-preview.mp4"
    assert data[0]["merged_source_names"] == ["part-a.mp4", "part-b.mp4"]
    assert data[0]["content_subject"] == "傲雷 司令官2 Ultra · 户外照明"
    assert data[0]["content_summary"] == "这是任务列表需要显示的摘要。"
    assert data[0]["quality_summary"] == "B 88.0 · 1 个扣分项"
    assert data[0]["avatar_delivery_status"] == "done"
    assert data[0]["auto_review_status"] == "blocked"
