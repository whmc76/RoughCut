from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import Artifact, Job, RenderOutput


@pytest.mark.asyncio
async def test_collect_job_report_prefers_artifacts_for_cover_and_platform_doc(db_engine, monkeypatch, tmp_path: Path):
    import scripts.run_fullchain_batch as batch_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    output_path = tmp_path / "demo_成片.mp4"
    cover_path = tmp_path / "demo_封面.jpg"
    publish_path = tmp_path / "demo_成片_publish.md"
    output_path.write_bytes(b"video")
    cover_path.write_bytes(b"cover")
    publish_path.write_text("# publish", encoding="utf-8")

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path=str(tmp_path / "source.mp4"),
                source_name="source.mp4",
                status="done",
                language="zh-CN",
            )
        )
        session.add(RenderOutput(job_id=job_id, status="done", progress=1.0, output_path=str(output_path)))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "cover": str(cover_path),
                    "cover_variants": [str(cover_path), str(tmp_path / "demo_封面_v2.jpg")],
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path=str(publish_path),
                data_json={"platforms": {}},
            )
        )
        await session.commit()

    monkeypatch.setattr(batch_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(batch_mod, "probe_duration", lambda path: 12.5)

    report = await batch_mod.collect_job_report(
        str(job_id),
        {"path": str(tmp_path / "source.mp4"), "source_name": "source.mp4"},
        [],
        "done",
    )

    assert report.output_path == str(output_path)
    assert report.cover_path == str(cover_path)
    assert report.platform_doc == str(publish_path)
    assert report.cover_variant_count == 2
    assert "封面已导出" in report.notes
    assert "平台文案已导出" in report.notes


@pytest.mark.asyncio
async def test_collect_job_report_emits_live_stage_validations_and_quality_summary(db_engine, monkeypatch, tmp_path: Path):
    import scripts.run_fullchain_batch as batch_mod
    from roughcut.db.models import JobStep, SubtitleItem, Timeline, TranscriptSegment

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    output_path = tmp_path / "demo_成片.mp4"
    output_path.write_bytes(b"video")

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path=str(tmp_path / "source.mp4"),
                source_name="source.mp4",
                status="done",
                language="zh-CN",
            )
        )
        for step_name in ("transcribe", "subtitle_postprocess", "content_profile", "edit_plan", "render", "platform_package"):
            session.add(JobStep(job_id=job_id, step_name=step_name, status="done"))
        session.add(RenderOutput(job_id=job_id, status="done", progress=1.0, output_path=str(output_path)))
        session.add(
            TranscriptSegment(
                job_id=job_id,
                version=1,
                segment_index=0,
                start_time=0.0,
                end_time=2.0,
                text="ARC 这把工具的单手开合很舒服",
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=2.0,
                text_raw="ARC 这把工具的单手开合很舒服",
            )
        )
        session.add(
            Timeline(
                job_id=job_id,
                timeline_type="editorial",
                data_json={"segments": [{"type": "keep", "start": 0.0, "end": 2.0}]},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "LEATHERMAN",
                    "subject_model": "ARC",
                    "subject_type": "多功能工具钳",
                    "video_theme": "ARC 上手体验",
                    "summary": "这条视频重点看 ARC 的上手体验和单手开合。",
                    "engagement_question": "你会在意这类工具的单手开合吗？",
                    "review_mode": "manual_confirmed",
                    "automation_review": {"score": 0.96},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "packaged_mp4": str(output_path),
                    "packaged_srt": str(tmp_path / "demo_成片.srt"),
                    "quality_checks": {
                        "subtitle_sync": {
                            "status": "ok",
                            "message": "成片字幕时间轴与视频时长基本匹配",
                            "warning_codes": [],
                        }
                    },
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path=str(tmp_path / "demo_成片_publish.md"),
                data_json={"platforms": {}},
            )
        )
        await session.commit()

    publish_path = tmp_path / "demo_成片_publish.md"
    publish_path.write_text("# publish", encoding="utf-8")

    monkeypatch.setattr(batch_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(batch_mod, "probe_duration", lambda path: 12.5)

    report = await batch_mod.collect_job_report(
        str(job_id),
        {"path": str(tmp_path / "source.mp4"), "source_name": "source.mp4"},
        [],
        "done",
    )

    assert report.quality_grade in {"A", "B"}
    assert report.quality_score is not None
    assert report.transcript_segment_count == 1
    assert all(item.status == "pass" for item in report.live_stage_validations)
    assert "live校验通过" in report.notes


def test_build_live_stage_validations_treats_missing_optional_review_steps_as_pass():
    import scripts.run_fullchain_batch as batch_mod

    validations = batch_mod.build_live_stage_validations(
        step_statuses={
            "transcribe": "done",
            "subtitle_postprocess": "done",
            "content_profile": "done",
            "edit_plan": "done",
            "render": "done",
            "platform_package": "done",
        },
        transcript_segment_count=1,
        subtitle_count=1,
        keep_ratio=1.0,
        profile={"summary": "ok"},
        platform_doc=__file__,
        subtitle_quality_report=None,
        subtitle_term_resolution_patch=None,
        subtitle_consistency_report=None,
        quality_assessment={"issue_codes": []},
    )

    status_by_stage = {item.stage: item.status for item in validations}

    assert status_by_stage["subtitle_term_resolution"] == "pass"
    assert status_by_stage["subtitle_consistency_review"] == "pass"
    assert status_by_stage["summary_review"] == "pass"
    assert status_by_stage["final_review"] == "pass"
