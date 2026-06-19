from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.creative.modes import (
    build_active_enhancement_mode_options,
    build_mode_catalog,
    normalize_enhancement_modes,
    resolve_live_batch_enhancement_modes,
)
import roughcut.pipeline.orchestrator as orchestrator
from roughcut.db.models import Artifact, Job, JobStep, SubtitleItem
from roughcut.db.session import Base
from roughcut.pipeline.steps import (
    _content_profile_confident_enough_to_skip_enrich,
    _drop_soft_content_understanding_blockers,
    _finalize_content_profile_review_state,
)
from roughcut.review.content_profile import assess_content_profile_automation
from roughcut.review.subtitle_quality import ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT


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
    assert "ai_director" not in {item["value"] for item in options}
    assert "ai_director" not in {item["key"] for item in catalog["enhancement_modes"]}


def test_legacy_auto_review_enhancement_mode_is_dropped_from_new_configs() -> None:
    assert normalize_enhancement_modes(["avatar_commentary", "auto_review", "ai_effects", "ai_director"]) == [
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


def test_content_understanding_timeout_blocks_auto_confirm() -> None:
    automation = assess_content_profile_automation(
        {
            "workflow_template": "edc_tactical",
            "subject_type": "EDC手电",
            "video_theme": "NITECORE EDC17UV开箱与亮度展示",
            "summary": "这条视频围绕 NITECORE EDC17UV 手电展开，介绍开箱、规格和亮度体验。",
            "cover_title": {"top": "NITECORE", "main": "EDC17UV", "bottom": "亮度表现直接看"},
            "engagement_question": "你更关注这类手电的亮度还是便携性？",
            "search_queries": ["NITECORE EDC17UV", "EDC17UV 手电"],
            "subject_brand": "NITECORE",
            "subject_model": "EDC17UV",
            "source_context": {"video_description": "任务创建时已填写视频说明。"},
            "content_understanding": {
                "needs_review": True,
                "review_reasons": ["内容理解调用超时"],
            },
        },
        subtitle_items=[{"text_final": "这是一段关于EDC17UV手电开箱和亮度体验的字幕。"} for _ in range(8)],
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        auto_confirm_enabled=True,
        threshold=0.92,
    )

    assert "内容理解调用超时" in automation["blocking_reasons"]
    assert automation["auto_confirm"] is False


def test_confident_content_profile_can_skip_enrich_pass() -> None:
    assert _content_profile_confident_enough_to_skip_enrich(
        {
            "subject_brand": "NITECORE",
            "subject_model": "EDC17",
            "subject_type": "EDC手电",
            "video_theme": "NITECORE EDC17开箱与EDC37对比",
            "summary": "这条视频围绕NITECORE EDC17手电展开，介绍开箱、功能和与EDC37的对比。",
            "search_queries": ["NITECORE EDC17", "EDC17 EDC37 对比"],
            "content_understanding": {
                "primary_subject": "NITECORE EDC17",
                "observed_entities": [{"name": "EDC17"}, {"name": "EDC37"}],
                "needs_review": False,
                "confidence": {"overall": 0.92},
            },
        }
    ) is True


def test_uncertain_content_profile_keeps_enrich_pass() -> None:
    assert _content_profile_confident_enough_to_skip_enrich(
        {
            "subject_type": "内容待确认",
            "video_theme": "开箱展示",
            "summary": "这是一条开箱展示视频。",
            "search_queries": [],
            "content_understanding": {
                "needs_review": True,
                "confidence": {"overall": 0.84},
            },
        }
    ) is False


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
async def test_edit_plan_does_not_wait_for_optional_creative_steps() -> None:
    job = Job(id=uuid.uuid4(), source_path="source.mp4", source_name="source.mp4", status="processing")
    steps = [
        JobStep(job_id=job.id, step_name="probe", status="done"),
        JobStep(job_id=job.id, step_name="extract_audio", status="done"),
        JobStep(job_id=job.id, step_name="transcribe", status="done"),
        JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
        JobStep(job_id=job.id, step_name="subtitle_term_resolution", status="done"),
        JobStep(job_id=job.id, step_name="subtitle_consistency_review", status="done"),
        JobStep(job_id=job.id, step_name="glossary_review", status="done"),
        JobStep(job_id=job.id, step_name="transcript_review", status="done"),
        JobStep(job_id=job.id, step_name="subtitle_translation", status="done"),
        JobStep(job_id=job.id, step_name="content_profile", status="done"),
        JobStep(job_id=job.id, step_name="summary_review", status="done"),
        JobStep(job_id=job.id, step_name="ai_director", status="skipped"),
        JobStep(job_id=job.id, step_name="avatar_commentary", status="pending"),
        JobStep(job_id=job.id, step_name="edit_plan", status="pending"),
    ]
    session = _FakeStepSession(job, steps)

    assert await orchestrator._is_step_ready(steps[-1], session) is True


def test_completed_summary_review_reconciles_stale_content_profile_failure() -> None:
    content_step = JobStep(
        job_id=uuid.uuid4(),
        step_name="content_profile",
        status="failed",
        attempt=3,
        error_message="步骤 content_profile 已达到最大重试次数 3，不再自动重试。",
        metadata_={"detail": "旧失败状态"},
    )
    review_step = JobStep(job_id=content_step.job_id, step_name="summary_review", status="done")

    orchestrator._reconcile_completed_summary_review_step(
        {
            "content_profile": content_step,
            "summary_review": review_step,
        }
    )

    assert content_step.status == "done"
    assert content_step.error_message is None
    assert content_step.metadata_["progress"] == 1.0


@pytest.mark.asyncio
async def test_failed_job_with_completed_summary_review_recovers_for_edit_plan_dispatch() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(
                id=uuid.uuid4(),
                source_path="source.mp4",
                source_name="source.mp4",
                status="failed",
                error_message="content_profile 已失败",
            )
            steps = [
                JobStep(job_id=job.id, step_name="probe", status="done"),
                JobStep(job_id=job.id, step_name="extract_audio", status="done"),
                JobStep(job_id=job.id, step_name="transcribe", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_term_resolution", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_consistency_review", status="done"),
                JobStep(job_id=job.id, step_name="glossary_review", status="done"),
                JobStep(job_id=job.id, step_name="transcript_review", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_translation", status="done"),
                JobStep(
                    job_id=job.id,
                    step_name="content_profile",
                    status="failed",
                    attempt=3,
                    error_message="步骤 content_profile 已达到最大重试次数 3，不再自动重试。",
                ),
                JobStep(job_id=job.id, step_name="summary_review", status="done"),
                JobStep(job_id=job.id, step_name="edit_plan", status="pending"),
            ]
            session.add(job)
            session.add_all(steps)
            await session.commit()

            await orchestrator._update_job_statuses(session)
            await session.commit()

            assert job.status == "processing"
            assert job.error_message is None
            content_step = next(step for step in steps if step.step_name == "content_profile")
            assert content_step.status == "done"
            assert content_step.error_message is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_summary_review_records_advisory_on_blocking_exception() -> None:
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
    assert final_profile is not None
    assert final_profile["review_mode"] == "manual_adjustment_advisory"
    assert review_step.status == "done"
    assert review_step.metadata_["manual_adjustment_advisory"] is True
    assert "主体身份冲突" in str(review_step.metadata_["detail"])


@pytest.mark.asyncio
async def test_summary_review_quality_issue_records_advisory_without_auto_rerun() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(id=uuid.uuid4(), source_path="source.mp4", source_name="source.mp4", status="processing")
            steps = [
                JobStep(job_id=job.id, step_name="probe", status="done"),
                JobStep(job_id=job.id, step_name="extract_audio", status="done"),
                JobStep(job_id=job.id, step_name="transcribe", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_postprocess", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_term_resolution", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_consistency_review", status="done"),
                JobStep(job_id=job.id, step_name="glossary_review", status="done"),
                JobStep(job_id=job.id, step_name="transcript_review", status="done"),
                JobStep(job_id=job.id, step_name="subtitle_translation", status="done"),
                JobStep(job_id=job.id, step_name="content_profile", status="done"),
                JobStep(job_id=job.id, step_name="summary_review", status="pending"),
                JobStep(job_id=job.id, step_name="ai_director", status="pending"),
                JobStep(job_id=job.id, step_name="avatar_commentary", status="pending"),
                JobStep(job_id=job.id, step_name="edit_plan", status="pending"),
                JobStep(job_id=job.id, step_name="render", status="pending"),
                JobStep(job_id=job.id, step_name="final_review", status="pending"),
                JobStep(job_id=job.id, step_name="platform_package", status="pending"),
            ]
            session.add(job)
            session.add_all(steps)
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type="content_profile",
                    data_json={
                        "subject_type": "手电",
                        "video_theme": "Nitecore EDC17 与 EDC37 开箱对比",
                        "summary": "视频围绕 Nitecore EDC17 与 EDC37 的外观和使用差异展开。",
                        "engagement_question": "你更关注 EDC17 还是 EDC37？",
                    },
                )
            )
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
                    data_json={
                        "score": 64.0,
                        "blocking": True,
                        "blocking_reasons": ["可词级纠偏的热词/型号残留 6 处"],
                        "warning_reasons": [],
                        "metrics": {"bad_term_total": 6},
                    },
                )
            )
            session.add(
                SubtitleItem(
                    job_id=job.id,
                    item_index=0,
                    start_time=0.0,
                    end_time=2.0,
                    text_raw="今天对比 EDC17 和 EDC37。",
                    text_norm="今天对比 EDC17 和 EDC37。",
                    text_final="今天对比 EDC17 和 EDC37。",
                )
            )
            await session.commit()

            await orchestrator._update_job_statuses(session)
            await session.commit()

            assert job.status == "processing"
            step_map = {step.step_name: step for step in steps}
            assert step_map["subtitle_postprocess"].status == "done"
            assert step_map["summary_review"].status == "done"
            assert step_map["summary_review"].metadata_["manual_adjustment_advisory"] is True
            quality_artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.job_id == job.id, Artifact.artifact_type == "quality_assessment")
                )
            ).scalars().all()
            assert quality_artifacts[-1].data_json["auto_rerun_triggered"] is False
            assert quality_artifacts[-1].data_json["manual_adjustment_advisory"] is True
            assert quality_artifacts[-1].data_json["auto_rerun_skipped_reason"] == "disabled_quality_gate_advisory"
    finally:
        await engine.dispose()


def test_final_review_auto_advance_hook_is_removed_from_editing_orchestrator() -> None:
    assert not hasattr(orchestrator, "_auto_advance_final_review_after_render")
