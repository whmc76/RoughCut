from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_is_step_ready_allows_skipped_optional_predecessor(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/skipped-predecessor.mp4",
                source_name="skipped-predecessor.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="done"))
        session.add(JobStep(job_id=job_id, step_name="ai_director", status="skipped"))
        session.add(JobStep(job_id=job_id, step_name="avatar_commentary", status="skipped"))
        session.add(JobStep(job_id=job_id, step_name="edit_plan", status="pending"))
        await session.commit()

    async with factory() as session:
        edit_plan_step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "edit_plan",
                )
            )
        ).scalar_one()
        ready = await orchestrator_mod._is_step_ready(edit_plan_step, session)

    assert ready is True


@pytest.mark.asyncio
async def test_reset_job_for_quality_rerun_increments_review_round_and_clears_notification_fingerprint(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/review-round.mp4",
                source_name="review-round.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="glossary_review",
                status="done",
                metadata_={
                    "review_round": 1,
                    "telegram_review_notifications": {
                        "subtitle_review": {"round": 1, "signature": "old-subtitle"}
                    },
                },
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="final_review",
                status="pending",
                metadata_={
                    "review_round": 1,
                    "telegram_review_notifications": {
                        "final_review": {"round": 1, "signature": "old-final"}
                    },
                },
            )
        )
        await session.commit()

    async with factory() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id)
            )
        ).scalars().all()
        await orchestrator_mod._reset_job_for_quality_rerun(
            session,
            job,
            steps,
            rerun_steps=["glossary_review", "final_review"],
            issue_codes=["subtitle_terms"],
        )
        await session.commit()

    async with factory() as session:
        steps = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id)
            )
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}

        assert step_map["glossary_review"].metadata_["review_round"] == 2
        assert step_map["glossary_review"].metadata_["telegram_review_notifications"] == {}
        assert step_map["final_review"].metadata_["review_round"] == 2
        assert step_map["final_review"].metadata_["telegram_review_notifications"] == {}


@pytest.mark.asyncio
async def test_tick_respects_retry_wait_until_before_redispatch(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async def no_watch_duty():
        return {"roots_total": 0, "scan_started": 0, "auto_merged_jobs": 0, "auto_enqueued_jobs": 0, "idle_slots": 0}

    async def no_op(*args, **kwargs):
        return None

    async def ready_true(*args, **kwargs):
        return True

    async def zero(*args, **kwargs):
        return 0

    dispatched: list[str] = []

    async def fake_dispatch(step, session):
        dispatched.append(step.step_name)

    monkeypatch.setattr(watcher_mod, "run_watch_root_auto_duty", no_watch_duty)
    monkeypatch.setattr(orchestrator_mod, "_ensure_job_steps", no_op)
    monkeypatch.setattr(orchestrator_mod, "_update_job_statuses", no_op)
    monkeypatch.setattr(orchestrator_mod, "_is_step_ready", ready_true)
    monkeypatch.setattr(orchestrator_mod, "_dispatch_step", fake_dispatch)
    monkeypatch.setattr(orchestrator_mod, "_count_running_gpu_steps", zero)

    job_id = uuid.uuid4()
    wait_until = datetime.now(timezone.utc) + timedelta(minutes=3)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/demo.mp4",
                source_name="demo.mp4",
                status="pending",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="transcribe",
                status="pending",
                metadata_={"retry_wait_until": wait_until.timestamp()},
            )
        )
        await session.commit()

    await orchestrator_mod.tick()

    assert "transcribe" not in dispatched

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe")
            )
        ).scalar_one()
        assert step.status == "pending"
        assert "资源等待中" in str((step.metadata_ or {}).get("detail") or "")


@pytest.mark.asyncio
async def test_tick_defers_gpu_sensitive_step_when_dispatch_gpu_guard_blocks(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async def no_watch_duty():
        return {"roots_total": 0, "scan_started": 0, "auto_merged_jobs": 0, "auto_enqueued_jobs": 0, "idle_slots": 0}

    async def no_op(*args, **kwargs):
        return None

    async def ready_true(*args, **kwargs):
        return True

    async def zero(*args, **kwargs):
        return 0

    dispatched: list[str] = []

    async def fake_dispatch(step, session):
        dispatched.append(step.step_name)

    monkeypatch.setattr(watcher_mod, "run_watch_root_auto_duty", no_watch_duty)
    monkeypatch.setattr(orchestrator_mod, "_ensure_job_steps", no_op)
    monkeypatch.setattr(orchestrator_mod, "_update_job_statuses", no_op)
    monkeypatch.setattr(orchestrator_mod, "_is_step_ready", ready_true)
    monkeypatch.setattr(orchestrator_mod, "_dispatch_step", fake_dispatch)
    monkeypatch.setattr(orchestrator_mod, "_count_running_gpu_steps", zero)
    monkeypatch.setattr(
        orchestrator_mod,
        "_gpu_dispatch_wait_reason",
        lambda step_name, *, running_gpu_steps: "检测到外部 GPU 占用，当前步骤延后派发。" if step_name == "transcribe" else None,
    )

    job_id = uuid.uuid4()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/gpu.mp4",
                source_name="gpu.mp4",
                status="pending",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="pending"))
        await session.commit()

    await orchestrator_mod.tick()

    assert "transcribe" not in dispatched

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe")
            )
        ).scalar_one()
        assert step.status == "pending"
        assert "外部 GPU 占用" in str((step.metadata_ or {}).get("detail") or "")


@pytest.mark.asyncio
async def test_update_job_statuses_triggers_quality_rerun_for_generic_low_detail_profile(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Artifact, Job, SubtitleItem
    from roughcut.db.session import get_session_factory

    settings = orchestrator_mod.get_settings()
    object.__setattr__(settings, "quality_auto_rerun_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_below_score", 75.0)
    object.__setattr__(settings, "quality_auto_rerun_max_attempts", 1)

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/quality.mp4",
                source_name="quality.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            step.finished_at = now
            session.add(step)
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "开箱产品",
                    "video_theme": "开箱评测",
                    "summary": "围绕开箱产品展开，偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
                    "engagement_question": "你觉得值不值？",
                    "preset_name": "edc_tactical",
                    "automation_review": {"score": 0.62},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "packaged_mp4": "E:/tmp/quality.mp4",
                    "plain_mp4": "E:/tmp/quality_plain.mp4",
                    "ai_effect_mp4": "E:/tmp/quality_fx.mp4",
                    "avatar_result": {"status": "done", "detail": "ok"},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path="E:/tmp/quality_publish.md",
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=4.0,
                text_raw="Loop露普SK05二代UV版和一代做对比，亮度提升1000lm，续航三小时。",
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._update_job_statuses(session)
        await session.commit()

    async with factory() as session:
        job = (await session.execute(orchestrator_mod.select(Job).where(Job.id == job_id))).scalar_one()
        steps = (
            await session.execute(orchestrator_mod.select(orchestrator_mod.JobStep).where(orchestrator_mod.JobStep.job_id == job_id))
        ).scalars().all()
        artifacts = (
            await session.execute(
                orchestrator_mod.select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "quality_assessment")
            )
        ).scalars().all()

        step_map = {step.step_name: step for step in steps}
        latest_quality = next(item for item in artifacts if "auto_rerun_triggered" in (item.data_json or {}))

        assert job.status == "processing"
        assert step_map["probe"].status == "done"
        assert step_map["content_profile"].status == "pending"
        assert step_map["render"].status == "pending"
        assert step_map["final_review"].status == "pending"
        assert step_map["platform_package"].status == "pending"
        assert latest_quality.data_json["auto_rerun_triggered"] is True
        assert latest_quality.data_json["auto_rerun_step"] == "content_profile"


@pytest.mark.asyncio
async def test_update_job_statuses_respects_quality_rerun_max_attempts(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Artifact, Job, SubtitleItem
    from roughcut.db.session import get_session_factory

    settings = orchestrator_mod.get_settings()
    object.__setattr__(settings, "quality_auto_rerun_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_below_score", 75.0)
    object.__setattr__(settings, "quality_auto_rerun_max_attempts", 1)

    job_id = uuid.uuid4()
    signature = "comparison_blind|detail_blind|generic_question|generic_subject_type|generic_summary|generic_video_theme|low_profile_confidence"
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/quality-repeat.mp4",
                source_name="quality-repeat.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            step.finished_at = now
            session.add(step)
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "开箱产品",
                    "video_theme": "开箱评测",
                    "summary": "围绕开箱产品展开，偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
                    "engagement_question": "你觉得值不值？",
                    "preset_name": "edc_tactical",
                    "automation_review": {"score": 0.62},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "packaged_mp4": "E:/tmp/quality-repeat.mp4",
                    "plain_mp4": "E:/tmp/quality-repeat_plain.mp4",
                    "ai_effect_mp4": "E:/tmp/quality-repeat_fx.mp4",
                    "avatar_result": {"status": "done", "detail": "ok"},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path="E:/tmp/quality-repeat_publish.md",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "auto_rerun_count": 1,
                    "auto_rerun_history": [
                        {
                            "step": "content_profile",
                            "signature": signature,
                            "score": 41.0,
                        }
                    ],
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=4.0,
                text_raw="Loop露普SK05二代UV版和一代做对比，亮度提升1000lm，续航三小时。",
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._update_job_statuses(session)
        await session.commit()

    async with factory() as session:
        job = (await session.execute(orchestrator_mod.select(Job).where(Job.id == job_id))).scalar_one()
        steps = (
            await session.execute(orchestrator_mod.select(orchestrator_mod.JobStep).where(orchestrator_mod.JobStep.job_id == job_id))
        ).scalars().all()
        artifacts = (
            await session.execute(
                orchestrator_mod.select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "quality_assessment")
            )
        ).scalars().all()

        latest_quality = next(item for item in artifacts if "auto_rerun_triggered" in (item.data_json or {}))

        assert job.status == "done"
        assert all(step.status == "done" for step in steps)
        assert latest_quality.data_json["auto_rerun_triggered"] is False
        assert latest_quality.data_json["auto_rerun_skipped_reason"] == "max_attempts_reached"


@pytest.mark.asyncio
async def test_update_job_statuses_reruns_subtitle_chain_for_subtitle_quality_issue(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    settings = orchestrator_mod.get_settings()
    object.__setattr__(settings, "quality_auto_rerun_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_below_score", 90.0)
    object.__setattr__(settings, "quality_auto_rerun_max_attempts", 1)

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/subtitle-only.mp4",
                source_name="subtitle-only.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            step.finished_at = now
            session.add(step)
        session.add(
            Artifact(
                job_id=job_id,
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
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="subtitle_translation",
                data_json={"item_count": 12, "target_language": "en"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path="E:/tmp/subtitle-only_publish.md",
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._update_job_statuses(session)
        await session.commit()

    async with factory() as session:
        job = (await session.execute(orchestrator_mod.select(Job).where(Job.id == job_id))).scalar_one()
        steps = (
            await session.execute(orchestrator_mod.select(orchestrator_mod.JobStep).where(orchestrator_mod.JobStep.job_id == job_id))
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}
        artifacts = (
            await session.execute(
                orchestrator_mod.select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "quality_assessment")
            )
        ).scalars().all()
        latest_quality = next(item for item in artifacts if "auto_rerun_triggered" in (item.data_json or {}))

        assert job.status == "processing"
        assert step_map["subtitle_postprocess"].status == "pending"
        assert step_map["glossary_review"].status == "pending"
        assert step_map["subtitle_translation"].status == "pending"
        assert step_map["content_profile"].status == "pending"
        assert step_map["edit_plan"].status == "pending"
        assert step_map["ai_director"].status == "pending"
        assert step_map["avatar_commentary"].status == "pending"
        assert step_map["render"].status == "pending"
        assert step_map["final_review"].status == "pending"
        assert step_map["platform_package"].status == "pending"
        assert latest_quality.data_json["auto_rerun_triggered"] is True
        assert latest_quality.data_json["auto_rerun_steps"] == [
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
