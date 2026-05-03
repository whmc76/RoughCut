from __future__ import annotations

import uuid

import pytest

from roughcut.creative.modes import (
    build_active_enhancement_mode_options,
    build_mode_catalog,
    normalize_enhancement_modes,
    resolve_live_batch_enhancement_modes,
)
import roughcut.pipeline.orchestrator as orchestrator
from roughcut.db.models import Job, JobStep
from roughcut.pipeline.steps import _drop_soft_content_understanding_blockers, _finalize_content_profile_review_state
from roughcut.review.content_profile import assess_content_profile_automation


class _FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _FakeExecuteResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _FakeScalarResult(self._values)


class _FakeStepSession:
    def __init__(self, job, steps):
        self._job = job
        self._steps = steps

    async def get(self, model, id_):
        return self._job if model is Job and id_ == self._job.id else None

    async def execute(self, _stmt):
        return _FakeExecuteResult(self._steps)


def test_auto_review_is_not_a_selectable_enhancement_mode() -> None:
    options = build_active_enhancement_mode_options()
    catalog = build_mode_catalog()

    assert "auto_review" not in {item["value"] for item in options}
    assert "auto_review" not in {item["key"] for item in catalog["enhancement_modes"]}


def test_legacy_auto_review_enhancement_mode_is_dropped_from_new_configs() -> None:
    assert normalize_enhancement_modes(["avatar_commentary", "auto_review", "ai_effects"]) == [
        "avatar_commentary",
        "ai_effects",
    ]
    assert "auto_review" not in resolve_live_batch_enhancement_modes(None)


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


def test_content_understanding_inference_failure_is_warning_not_blocking() -> None:
    automation = assess_content_profile_automation(
        {
            "workflow_template": "edc_tactical",
            "subject_type": "EDC机能包",
            "video_theme": "HSJUN BOLTBOAT 影蚀机能单肩包体验",
            "summary": "这条视频围绕 HSJUN BOLTBOAT 影蚀机能单肩包展开，介绍外观、容量和日常使用体验。",
            "cover_title": {"title": "影蚀机能单肩包体验", "subtitle": "外观与使用细节"},
            "engagement_question": "你最关注这款包的哪个细节？",
            "search_queries": ["HSJUN BOLTBOAT 影蚀", "机能单肩包"],
            "subject_brand": "BOLTBOAT",
            "subject_model": "影蚀",
            "source_context": {"video_description": "任务创建时已填写视频说明。"},
            "content_understanding": {
                "needs_review": True,
                "review_reasons": ["内容理解推断失败"],
            },
        },
        subtitle_items=[{"text_final": "这是一段关于机能单肩包外观和使用体验的字幕。"} for _ in range(8)],
        source_name="IMG_0185 HSJUN BOLTBOAT勃朗峰户外 影蚀 机能单肩包轻量化斜挎包.MOV",
        auto_confirm_enabled=True,
        threshold=0.92,
    )

    assert "内容理解推断失败" in automation["review_reasons"]
    assert automation["blocking_reasons"] == []
    assert automation["auto_confirm"] is True


def test_llm_food_domain_wins_over_edc_keyword_conflict() -> None:
    automation = assess_content_profile_automation(
        {
            "workflow_template": "unboxing_standard",
            "subject_domain": "food",
            "subject_brand": "LuckyKiss",
            "subject_model": "edc弹射舱益生菌含片",
            "subject_type": "弹射益生菌含片",
            "video_theme": "LuckyKiss弹射益生菌含片功能演示",
            "summary": "这条视频围绕 LuckyKiss edc弹射舱益生菌含片展开，EDC 只是包装和携带场景。",
            "cover_title": {"top": "LUCKYKISS", "main": "edc弹射舱益生菌含片", "bottom": "收纳装载直接看"},
            "engagement_question": "你会把这种含片放进日常随身小物里吗？",
            "search_queries": ["LuckyKiss 益生菌含片", "edc弹射舱益生菌含片"],
            "content_understanding": {
                "content_domain": "food",
                "needs_review": False,
            },
        },
        subtitle_items=[
            {"text_final": "这是 LUCKYKISS 的一个口香糖。"},
            {"text_final": "也是一个益生菌含片。"},
            {"text_final": "它做成了 EDC 弹射舱的样子。"},
        ]
        * 3,
        source_name="IMG_0024 luckykiss edc弹射舱 益生菌含片.MOV",
        auto_confirm_enabled=True,
        threshold=0.92,
    )

    assert "字幕显示为含片/益生菌等入口产品，但当前摘要主体仍落在装备/工具类" not in automation["blocking_reasons"]
    assert automation["auto_confirm"] is True


def test_soft_content_understanding_blocker_is_dropped_before_exception_gate() -> None:
    automation = _drop_soft_content_understanding_blockers(
        {
            "score": 1.0,
            "threshold": 0.92,
            "auto_confirm": False,
            "quality_gate_passed": False,
            "review_reasons": [],
            "blocking_reasons": ["内容理解推断失败"],
        }
    )

    assert automation["blocking_reasons"] == []
    assert automation["auto_confirm"] is True
    assert automation["quality_gate_passed"] is True


def test_first_seen_identity_warning_does_not_block_exception_gate() -> None:
    automation = assess_content_profile_automation(
        {
            "workflow_template": "edc_tactical",
            "subject_type": "EDC折刀",
            "video_theme": "NOC MT332细节展示",
            "summary": "这条视频围绕 NOC MT332 折刀的外观和细节展示展开。",
            "cover_title": {"title": "NOC MT332细节", "subtitle": "外观展示"},
            "engagement_question": "你更关注这款折刀的哪个细节？",
            "search_queries": ["NOC MT332", "NOC 折刀"],
            "subject_brand": "NOC",
            "subject_model": "MT332",
            "identity_review": {
                "required": True,
                "conservative_summary": True,
                "reason": "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
            },
            "content_understanding": {
                "needs_review": True,
                "review_reasons": ["开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"],
            },
        },
        subtitle_items=[{"text_final": "展示一下这款折刀的外观细节。"} for _ in range(8)],
        source_name="VID_20260112_122408 室内光线展示 NOC MT33两款折刀的外观和细节.mp4",
        auto_confirm_enabled=True,
        threshold=0.92,
    )

    assert "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认" in automation["review_reasons"]
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
async def test_smart_assist_pauses_before_render_dispatch() -> None:
    job = Job(
        id=uuid.uuid4(),
        source_path="source.mp4",
        source_name="source.mp4",
        status="processing",
        job_flow_mode="smart_assist",
    )
    edit_plan_step = JobStep(job_id=job.id, step_name="edit_plan", status="done")
    render_step = JobStep(job_id=job.id, step_name="render", status="pending")
    session = _FakeStepSession(job, [edit_plan_step, render_step])

    paused = await orchestrator._step_paused_for_smart_assist(render_step, session)

    assert paused is True
    assert job.status == "awaiting_manual_edit"
    assert render_step.metadata_["manual_editor_required"] is True


@pytest.mark.asyncio
async def test_smart_assist_manual_editor_apply_releases_render_dispatch() -> None:
    job = Job(
        id=uuid.uuid4(),
        source_path="source.mp4",
        source_name="source.mp4",
        status="processing",
        job_flow_mode="smart_assist",
    )
    edit_plan_step = JobStep(job_id=job.id, step_name="edit_plan", status="done")
    render_step = JobStep(
        job_id=job.id,
        step_name="render",
        status="pending",
        metadata_={"rerun_requested_via": "manual_editor"},
    )
    session = _FakeStepSession(job, [edit_plan_step, render_step])

    paused = await orchestrator._step_paused_for_smart_assist(render_step, session)

    assert paused is False
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
