from __future__ import annotations

import uuid

import pytest

import roughcut.pipeline.orchestrator as orchestrator
from roughcut.db.models import Job, JobStep
from roughcut.pipeline.steps import _finalize_content_profile_review_state
from roughcut.review.content_profile import assess_content_profile_automation


def test_product_identity_gap_is_warning_not_blocking_review() -> None:
    automation = assess_content_profile_automation(
        {
            "workflow_template": "unboxing_standard",
            "subject_type": "内容待确认",
            "video_theme": "开箱展示",
            "summary": "这是一段开箱展示视频",
            "engagement_question": "你最想先看哪处细节？",
            "source_context": {"video_description": "用户已在任务创建时填写视频说明。"},
        },
        subtitle_items=[{"text_final": "今天看一下这个新到的东西"} for _ in range(6)],
        source_name="开箱展示.mp4",
        auto_confirm_enabled=True,
        threshold=0.9,
    )

    assert "开箱类视频未识别出可验证主体" in automation["review_reasons"]
    assert automation["blocking_reasons"] == []
    assert automation["auto_confirm"] is True


@pytest.mark.asyncio
async def test_summary_review_auto_completes_when_only_warnings_exist() -> None:
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing")
    content_step = JobStep(job_id=job.id, step_name="content_profile", status="done")
    review_step = JobStep(job_id=job.id, step_name="summary_review", status="pending")

    auto_confirmed, final_profile, _context_profile = await _finalize_content_profile_review_state(
        None,
        job=job,
        step=content_step,
        review_step=review_step,
        content_profile={"summary": "低置信度但没有阻塞异常"},
        automation={
            "auto_confirm": False,
            "score": 0.42,
            "threshold": 0.9,
            "review_reasons": ["摘要信息偏薄"],
            "blocking_reasons": [],
        },
        manual_review_feedback={},
        resolved_manual_review_feedback={},
        manual_review_draft_profile={},
    )

    assert auto_confirmed is True
    assert final_profile is not None
    assert final_profile["review_mode"] == "auto_confirmed"
    assert review_step.status == "done"
    assert review_step.metadata_["exception_only_auto_confirmed"] is True
    assert job.status == "processing"


@pytest.mark.asyncio
async def test_summary_review_pauses_on_blocking_exception() -> None:
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing")
    content_step = JobStep(job_id=job.id, step_name="content_profile", status="done")
    review_step = JobStep(job_id=job.id, step_name="summary_review", status="pending")

    auto_confirmed, final_profile, _context_profile = await _finalize_content_profile_review_state(
        None,
        job=job,
        step=content_step,
        review_step=review_step,
        content_profile={"summary": "主体存在冲突"},
        automation={
            "auto_confirm": False,
            "score": 0.91,
            "threshold": 0.9,
            "review_reasons": [],
            "blocking_reasons": ["主体身份冲突"],
            "identity_review": {"required": True, "reason": "主体身份冲突"},
        },
        manual_review_feedback={},
        resolved_manual_review_feedback={},
        manual_review_draft_profile={},
    )

    assert auto_confirmed is False
    assert final_profile is None
    assert review_step.status == "pending"
    assert "主体身份冲突" in str(review_step.metadata_["detail"])


@pytest.mark.asyncio
async def test_final_review_auto_advances_when_quality_gate_passes(monkeypatch) -> None:
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing")
    final_review_step = JobStep(job_id=job.id, step_name="final_review", status="pending")

    async def fake_assess(*_args, **_kwargs):
        return "done"

    monkeypatch.setattr(orchestrator, "_assess_and_maybe_rerun_job", fake_assess)

    outcome = await orchestrator._auto_advance_final_review_after_render(
        None,
        job=job,
        steps=[final_review_step],
        final_review_step=final_review_step,
    )

    assert outcome == "advanced"
    assert final_review_step.status == "done"
    assert final_review_step.metadata_["exception_only_auto_approved"] is True
    assert job.status == "processing"


@pytest.mark.asyncio
async def test_final_review_pauses_only_on_quality_exception(monkeypatch) -> None:
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing")
    final_review_step = JobStep(job_id=job.id, step_name="final_review", status="pending")
    notifications: list[tuple[str, str]] = []

    async def fake_assess(*_args, **_kwargs):
        return "needs_review"

    def fake_enqueue_review_notification(*, kind: str, job_id: str, **_kwargs):
        notifications.append((kind, job_id))

    monkeypatch.setattr(orchestrator, "_assess_and_maybe_rerun_job", fake_assess)
    monkeypatch.setattr(orchestrator, "enqueue_review_notification", fake_enqueue_review_notification)

    outcome = await orchestrator._auto_advance_final_review_after_render(
        None,
        job=job,
        steps=[final_review_step],
        final_review_step=final_review_step,
    )

    assert outcome == "needs_review"
    assert final_review_step.status == "pending"
    assert final_review_step.metadata_["exception_gate"] is True
    assert job.status == "needs_review"
    assert notifications == [("final_review", str(job.id))]
