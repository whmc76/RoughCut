from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep, SubtitleItem, Timeline
from roughcut.pipeline.steps import (
    _get_cover_seek,
    _load_latest_artifact,
    _load_latest_optional_artifact,
    _resolve_subtitle_split_profile,
    _load_latest_timeline,
    _record_source_integrity,
    _select_cover_source_video,
    _select_preferred_content_profile_artifact,
    run_ai_director,
    run_avatar_commentary,
    run_content_profile,
    run_glossary_review,
)


def test_resolve_subtitle_split_profile_prefers_faster_portrait_subtitles():
    portrait = _resolve_subtitle_split_profile(width=1080, height=1920)
    landscape = _resolve_subtitle_split_profile(width=1920, height=1080)

    assert portrait["orientation"] == "portrait"
    assert portrait["max_duration"] < landscape["max_duration"]
    assert portrait["max_chars"] < landscape["max_chars"]
    assert portrait["max_chars"] == 12
    assert landscape["max_chars"] == 18


def test_record_source_integrity_writes_debug_report(tmp_path: Path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"roughcut")
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()

    actual_hash = _record_source_integrity(
        source,
        source_ref="jobs/123/video.mp4",
        expected_hash=None,
        debug_dir=debug_dir,
        downloaded=True,
    )

    payload = json.loads((debug_dir / "source.integrity.json").read_text(encoding="utf-8"))
    assert payload["actual_sha256"] == actual_hash
    assert payload["downloaded_from_storage"] is True
    assert payload["hash_match"] is True


def test_record_source_integrity_rejects_hash_mismatch(tmp_path: Path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"roughcut")

    with pytest.raises(ValueError, match="Downloaded source hash mismatch"):
        _record_source_integrity(
            source,
            source_ref="jobs/123/video.mp4",
            expected_hash="deadbeef",
            debug_dir=None,
            downloaded=True,
        )


@pytest.mark.asyncio
async def test_run_glossary_review_loads_recent_subtitles_without_name_error(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    captured_recent_subtitles: list[dict] = []

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="glossary_review", status="running"))
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="OLIGHT",
                text_norm="OLIGHT",
                text_final="OLIGHT",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "OLIGHT傲雷",
                    "subject_model": "SLIM二代凹卡版",
                    "subject_type": "手电筒",
                    "video_theme": "手电筒开箱与上手体验",
                    "preset_name": "edc_tactical",
                },
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    async def fake_apply_glossary_corrections(*args, **kwargs):
        return []

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return [{"text_final": "历史字幕"}]

    async def fake_load_related_profile_subtitle_examples(*args, **kwargs):
        return [{"text_final": "相似字幕"}]

    async def fake_enrich_content_profile(**kwargs):
        return kwargs["profile"]

    monkeypatch.setattr(steps_mod, "apply_glossary_corrections", fake_apply_glossary_corrections)
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "_load_related_profile_subtitle_examples", fake_load_related_profile_subtitle_examples)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)

    def fake_build_subtitle_review_memory(**kwargs):
        captured_recent_subtitles.extend(kwargs["recent_subtitles"])
        return {"recent_subtitles_count": len(kwargs["recent_subtitles"])}

    async def fake_polish_subtitle_items(*args, **kwargs):
        assert kwargs["review_memory"]["recent_subtitles_count"] == 3
        assert kwargs["allow_llm"] is False
        return 1

    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)

    result = await run_glossary_review(str(job_id))

    assert result["polished_count"] == 1
    assert result["auto_accepted_correction_count"] == 0
    assert result["pending_correction_count"] == 0
    assert len(captured_recent_subtitles) == 3


@pytest.mark.asyncio
async def test_run_content_profile_auto_confirms_high_confidence_profile(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="screen_tutorial",
                enhancement_modes=["auto_review"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        for index, text in enumerate(
            [
                "这期演示剪映里怎么批量处理字幕样式",
                "先导入字幕模板再统一调整字号",
                "第二步要把描边和阴影一起改掉",
                "第三步检查时间轴里有没有错位",
                "最后导出预设方便下次复用",
                "这样整个流程就能稳定复现",
            ]
        ):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.0,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "preset_name": "screen_tutorial",
            "subject_type": "剪映字幕工作流",
            "video_theme": "批量字幕样式调整步骤讲解",
            "summary": "这条视频主要围绕剪映字幕工作流展开，重点讲清批量调样式、检查错位和复用预设的完整步骤。",
            "engagement_question": "你做批量字幕时最容易卡在样式统一还是时间轴检查？",
            "search_queries": ["剪映 批量字幕 样式", "剪映 字幕 预设 导出"],
            "cover_title": {"top": "剪映", "main": "批量字幕流程", "bottom": "样式统一教程"},
            "evidence": [{"title": "剪映字幕文档"}],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["auto_confirmed"] is True
    assert result["automation_score"] >= 0.72

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc())
        )
        artifacts = artifact_result.scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}
        assert set(artifact_map) == {"content_profile_draft", "content_profile_final"}

        draft = artifact_map["content_profile_draft"]
        final = artifact_map["content_profile_final"]
        assert draft["automation_review"]["auto_confirm"] is True
        assert draft["creative_profile"]["workflow_mode"] == "standard_edit"
        assert draft["creative_profile"]["enhancement_modes"] == ["auto_review"]
        assert final["review_mode"] == "auto_confirmed"

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "done"
        assert review_step.metadata_["auto_confirmed"] is True


@pytest.mark.asyncio
async def test_run_content_profile_keeps_manual_review_when_auto_review_mode_disabled(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="screen_tutorial",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        for index, text in enumerate(
            [
                "这期演示剪映里怎么批量处理字幕样式",
                "先导入字幕模板再统一调整字号",
                "第二步要把描边和阴影一起改掉",
                "第三步检查时间轴里有没有错位",
                "最后导出预设方便下次复用",
                "这样整个流程就能稳定复现",
            ]
        ):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.0,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "preset_name": "screen_tutorial",
            "subject_type": "剪映字幕工作流",
            "video_theme": "批量字幕样式调整步骤讲解",
            "summary": "这条视频主要围绕剪映字幕工作流展开，重点讲清批量调样式、检查错位和复用预设的完整步骤。",
            "engagement_question": "你做批量字幕时最容易卡在样式统一还是时间轴检查？",
            "search_queries": ["剪映 批量字幕 样式", "剪映 字幕 预设 导出"],
            "cover_title": {"top": "剪映", "main": "批量字幕流程", "bottom": "样式统一教程"},
            "evidence": [{"title": "剪映字幕文档"}],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["auto_confirmed"] is False
    assert result["automation_score"] >= 0.72

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc())
        )
        artifacts = artifact_result.scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}
        assert set(artifact_map) == {"content_profile_draft"}
        assert artifact_map["content_profile_draft"]["automation_review"]["auto_confirm"] is False

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "pending"
        assert review_step.metadata_ is None


@pytest.mark.asyncio
async def test_run_content_profile_passes_effective_glossary_terms_into_inference(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="unboxing_default",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            GlossaryTerm(
                wrong_forms=["鸿福", "狐蝠"],
                correct_form="狐蝠工业",
                category="bag_brand",
                context_hint="主流机能包品牌",
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这期鸿福 F叉二一小副包做个开箱测评。",
                text_norm="这期鸿福 F叉二一小副包做个开箱测评。",
                text_final="这期鸿福 F叉二一小副包做个开箱测评。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        captured["glossary_terms"] = kwargs.get("glossary_terms")
        return {
            "preset_name": "unboxing_default",
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业FXX1小副包开箱与上手评测",
            "summary": "这条视频主要围绕狐蝠工业 FXX1小副包展开，重点看分仓、挂点和日常收纳。",
            "engagement_question": "你更看重副包的分仓还是挂点？",
            "search_queries": ["狐蝠工业 FXX1小副包"],
            "cover_title": {"top": "狐蝠工业", "main": "FXX1小副包", "bottom": "分仓挂点先看"},
            "evidence": [{"title": "狐蝠工业 FXX1小副包"}],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["subject_brand"] == "狐蝠工业"
    assert any(
        item.get("correct_form") == "狐蝠工业"
        for item in list(captured.get("glossary_terms") or [])
    )


@pytest.mark.asyncio
async def test_run_content_profile_blocks_auto_confirm_for_first_seen_product_identity(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="IMG_0025.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="unboxing_default",
                enhancement_modes=["auto_review"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            GlossaryTerm(
                wrong_forms=["鸿福", "狐蝠"],
                correct_form="狐蝠工业",
                category="bag_brand",
                context_hint="主流机能包品牌",
            )
        )
        session.add(
            GlossaryTerm(
                wrong_forms=["F叉二一小副包"],
                correct_form="FXX1小副包",
                category="bag_model",
                context_hint="机能包型号",
            )
        )
        for index, text in enumerate(
            [
                "这期鸿福 F叉二一小副包做个开箱测评。",
                "重点看分仓和挂点设计。",
                "日常收纳会更直观一点。",
                "整体装载和细节也都聊一下。",
                "最后再说说通勤场景适不适合。",
                "这次主要还是上手体验。",
            ]
        ):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.0,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "preset_name": "unboxing_default",
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业FXX1小副包开箱与上手评测",
            "summary": "这条视频主要围绕狐蝠工业 FXX1小副包展开，重点看分仓、挂点和日常收纳。",
            "engagement_question": "你更看重副包的分仓还是挂点？",
            "search_queries": ["狐蝠工业 FXX1小副包", "FXX1小副包 开箱"],
            "cover_title": {"top": "狐蝠工业", "main": "FXX1小副包", "bottom": "分仓挂点先看"},
            "evidence": [],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["auto_confirmed"] is False

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
        )
        draft = artifact_result.scalar_one()
        assert "具体品牌型号待人工确认" in draft.data_json["summary"]
        assert draft.data_json["automation_review"]["identity_review"]["required"] is True

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "pending"
        assert "首次品牌/型号" in review_step.metadata_["detail"]


@pytest.mark.asyncio
async def test_run_subtitle_translation_generates_english_artifact_when_enabled(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
                enhancement_modes=["multilingual_translation"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="subtitle_translation", status="running"))
        for index, text in enumerate(["这是第一句。", "这是第二句。"]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.2,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_translate_subtitle_items(subtitle_items, *, target_language=None, target_language_mode="auto", preferred_ui_language="zh-CN"):
        assert target_language_mode == "auto"
        assert preferred_ui_language == "zh-CN"
        return {
            "target_language": "en",
            "target_language_mode": "auto",
            "source_language": "zh-CN",
            "item_count": 2,
            "items": [
                {"index": 0, "text_source": "这是第一句。", "text_translated": "This is the first line."},
                {"index": 1, "text_source": "这是第二句。", "text_translated": "This is the second line."},
            ],
        }

    monkeypatch.setattr(steps_mod, "translate_subtitle_items", fake_translate_subtitle_items)

    result = await steps_mod.run_subtitle_translation(str(job_id))

    assert result["enabled"] is True
    assert result["source_language"] == "zh-CN"
    assert result["target_language_mode"] == "auto"
    assert result["target_language"] == "en"
    assert result["translated_count"] == 2

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "subtitle_translation")
        )
        artifact = artifact_result.scalar_one()
        assert artifact.data_json["target_language"] == "en"
        assert artifact.data_json["target_language_mode"] == "auto"
        assert artifact.data_json["items"][0]["text_translated"] == "This is the first line."


@pytest.mark.asyncio
async def test_run_subtitle_translation_skips_when_mode_disabled(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="subtitle_translation", status="running"))
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    result = await steps_mod.run_subtitle_translation(str(job_id))

    assert result == {"enabled": False, "skipped": True}

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "subtitle_translation")
        )
        assert artifact_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_run_subtitle_translation_skips_when_source_matches_target_language(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="en-US",
                enhancement_modes=["multilingual_translation"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="subtitle_translation", status="running"))
        for index, text in enumerate(["This is the first line.", "This is the second line."]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.2,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        steps_mod,
        "get_settings",
        lambda: SimpleNamespace(preferred_ui_language="en-US"),
    )

    async def fail_translate_subtitle_items(*args, **kwargs):
        raise AssertionError("translate_subtitle_items should not be called when source and target match")

    monkeypatch.setattr(steps_mod, "translate_subtitle_items", fail_translate_subtitle_items)

    result = await steps_mod.run_subtitle_translation(str(job_id))

    assert result["enabled"] is True
    assert result["skipped"] is True
    assert result["reason"] == "same_language"
    assert result["source_language"] == "en-US"
    assert result["target_language"] == "en"
    assert result["translated_count"] == 0

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "subtitle_translation")
        )
        assert artifact_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_run_content_profile_prefers_seeded_profile_from_early_glossary(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="E:/videos/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile",
                data_json={
                    "subject_brand": "Loop露普",
                    "subject_model": "SK05二代Pro UV版",
                    "subject_type": "手电",
                    "video_theme": "手电开箱评测",
                    "preset_name": "edc_tactical",
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="Loop露普SK05二代Pro UV版",
                text_norm="Loop露普SK05二代Pro UV版",
                text_final="Loop露普SK05二代Pro UV版",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fail_infer_content_profile(**kwargs):
        raise AssertionError("infer_content_profile should not run when a seeded profile exists")

    async def fake_enrich_content_profile(**kwargs):
        profile = dict(kwargs["profile"])
        profile["engagement_question"] = "你更看重 UV 还是主灯？"
        return profile

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fail_infer_content_profile)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["subject_brand"] == "Loop露普"
    assert result["subject_model"] == "SK05二代Pro UV版"

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
        )
        draft = artifact_result.scalar_one()
        assert draft.data_json["subject_brand"] == "Loop露普"
        assert draft.data_json["engagement_question"] == "你更看重 UV 还是主灯？"


@pytest.mark.asyncio
async def test_run_ai_director_generates_plan_for_enabled_job(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/director.mp4",
                source_name="director.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=["ai_director"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="ai_director", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "科普讲解",
                    "summary": "讲清楚一个复杂概念的关键判断路径。",
                    "engagement_question": "你会怎么解释给第一次接触的人？",
                },
            )
        )
        for index, text in enumerate(["先说结论", "中间补背景", "最后抛问题"]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index) * 3,
                    end_time=float(index) * 3 + 2.0,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_build_ai_director_plan(**kwargs):
        return {
            "opening_hook": "这条内容最该先讲清楚的结论，我先替你拎出来。",
            "bridge_line": "这里应该补一层背景说明。",
            "voice_provider": "indextts2",
            "voiceover_segments": [{"segment_id": "director_hook", "rewritten_text": "新钩子"}],
            "dubbing_request": {"provider": "indextts2"},
        }

    monkeypatch.setattr(steps_mod, "build_ai_director_plan", fake_build_ai_director_plan)

    result = await run_ai_director(str(job_id))

    assert result["enabled"] is True
    assert result["voiceover_segment_count"] == 1

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("ai_director_plan",))
        assert artifact is not None
        assert artifact.data_json["voice_provider"] == "indextts2"


@pytest.mark.asyncio
async def test_run_avatar_commentary_generates_plan_for_enabled_job(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/avatar.mp4",
                source_name="avatar.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=["avatar_commentary", "ai_director"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="avatar_commentary", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "summary": "这是对复杂信息的拆解。",
                    "engagement_question": "你最想让数字人补哪一段？",
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="ai_director_plan",
                data_json={
                    "voiceover_segments": [
                        {
                            "purpose": "hook",
                            "rewritten_text": "我先替你抓重点。",
                            "suggested_start_time": 0.4,
                            "target_duration_sec": 3.2,
                        }
                    ]
                },
            )
        )
        for index, text in enumerate(["开头", "中段", "结尾"]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index) * 4,
                    end_time=float(index) * 4 + 2.5,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    def fake_build_avatar_commentary_plan(**kwargs):
        return {
            "provider": "heygem",
            "layout_template": "picture_in_picture_right",
            "segments": [{"segment_id": "avatar_1", "script": "我先替你抓重点。"}],
            "render_request": {"provider": "heygem"},
        }

    monkeypatch.setattr(steps_mod, "build_avatar_commentary_plan", fake_build_avatar_commentary_plan)

    result = await run_avatar_commentary(str(job_id))

    assert result["enabled"] is True
    assert result["segment_count"] == 1

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("avatar_commentary_plan",))
        assert artifact is not None
        assert artifact.data_json["layout_template"] == "picture_in_picture_right"


@pytest.mark.asyncio
async def test_run_avatar_commentary_segmented_passthrough_renders_only_once(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_source = tmp_path / "source.wav"
    audio_source.write_bytes(b"wav")
    provider_calls: list[dict] = []

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/avatar.mp4",
                source_name="avatar.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=["avatar_commentary"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="avatar_commentary", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/source.wav",
                data_json={},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={"summary": "数字人解说测试"},
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=2.0,
                text_raw="测试字幕",
                text_norm="测试字幕",
                text_final="测试字幕",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    def fake_build_avatar_commentary_plan(**kwargs):
        return {
            "provider": "heygem",
            "mode": "segmented_audio_passthrough",
            "layout_template": "picture_in_picture_right",
            "segments": [
                {
                    "segment_id": "avatar_seg_001",
                    "script": "测试字幕",
                    "start_time": 0.0,
                    "end_time": 2.0,
                    "duration_sec": 2.0,
                    "purpose": "commentary",
                }
            ],
            "render_request": {"provider": "heygem"},
        }

    class FakeStorage:
        async def async_download_file(self, storage_path, local_path):
            Path(local_path).write_bytes(audio_source.read_bytes())

    async def fake_extract_audio_clip(source_audio_path, clip_path, start_time, end_time):
        Path(clip_path).write_bytes(b"clip")

    def fake_select_default_avatar_profile():
        return {"id": "profile-1", "display_name": "测试数字人"}

    def fake_pick_avatar_profile_speaking_video_path(profile):
        presenter_path = tmp_path / "presenter.mp4"
        presenter_path.write_bytes(b"video")
        return presenter_path

    class FakeAvatarProvider:
        def execute_render(self, *, job_id, request):
            provider_calls.append(request)
            return {
                "provider": "heygem",
                "status": "success",
                "segments": [
                    {
                        "segment_id": "avatar_seg_001",
                        "status": "success",
                        "result": "/avatar_seg_001.mp4",
                        "local_result_path": str(tmp_path / "avatar_seg_001.mp4"),
                    }
                ],
            }

    monkeypatch.setattr(steps_mod, "build_avatar_commentary_plan", fake_build_avatar_commentary_plan)
    monkeypatch.setattr(steps_mod, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(steps_mod, "extract_audio_clip", fake_extract_audio_clip)
    monkeypatch.setattr(steps_mod, "_select_default_avatar_profile", fake_select_default_avatar_profile)
    monkeypatch.setattr(steps_mod, "_pick_avatar_profile_speaking_video_path", fake_pick_avatar_profile_speaking_video_path)
    monkeypatch.setattr(steps_mod, "get_avatar_provider", lambda: FakeAvatarProvider())

    result = await run_avatar_commentary(str(job_id))

    assert result["render_status"] == "success"
    assert len(provider_calls) == 1
    assert provider_calls[0]["segments"][0]["audio_url"].endswith("avatar_seg_001.wav")

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("avatar_commentary_plan",))
        assert artifact is not None
        assert artifact.data_json["render_execution"]["status"] == "success"
        assert artifact.data_json["segments"][0]["video_status"] == "success"
        assert artifact.data_json["segments"][0]["video_local_path"].endswith("avatar_seg_001.mp4")


@pytest.mark.asyncio
async def test_overlay_avatar_picture_in_picture_keeps_video_visible_without_corner_mask(tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    base_video = tmp_path / "base.mp4"
    avatar_video = tmp_path / "avatar.mp4"
    output_video = tmp_path / "output.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(base_video),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=120x160:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(avatar_video),
        ],
        check=True,
        capture_output=True,
    )

    await steps_mod._overlay_avatar_picture_in_picture(
        base_video_path=base_video,
        avatar_video_path=avatar_video,
        output_path=output_video,
        position="bottom_right",
        scale=0.28,
        margin=20,
        corner_radius=26,
        border_width=4,
        border_color="#F4E4B8",
    )

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(output_video), "-frames:v", "1", str(frame_path)],
        check=True,
        capture_output=True,
    )

    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(frame_path),
            "-vf",
            "crop=100:140:240:460,format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=False,
    )

    assert output_video.exists()
    assert probe.returncode == 0
    assert any(channel > 0 for channel in probe.stdout)


def _read_png_pixel(path: Path, x: int, y: int) -> tuple[int, int, int]:
    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"crop=1:1:{x}:{y},format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    pixel = probe.stdout[:3]
    assert len(pixel) == 3
    return pixel[0], pixel[1], pixel[2]


@pytest.mark.asyncio
async def test_overlay_avatar_picture_in_picture_applies_rounded_corners_and_border(tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    base_video = tmp_path / "base.mp4"
    avatar_video = tmp_path / "avatar.mp4"
    output_video = tmp_path / "output.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(base_video),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=120x160:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(avatar_video),
        ],
        check=True,
        capture_output=True,
    )

    await steps_mod._overlay_avatar_picture_in_picture(
        base_video_path=base_video,
        avatar_video_path=avatar_video,
        output_path=output_video,
        position="bottom_right",
        scale=0.28,
        margin=20,
        corner_radius=26,
        border_width=4,
        border_color="#F4E4B8",
    )

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(output_video), "-frames:v", "1", str(frame_path)],
        check=True,
        capture_output=True,
    )

    masked_corner_pixel = _read_png_pixel(frame_path, 145, 365)
    border_pixel = _read_png_pixel(frame_path, 158, 378)
    avatar_pixel = _read_png_pixel(frame_path, 170, 390)

    assert masked_corner_pixel == (0, 0, 0)
    assert border_pixel != (0, 0, 0)
    assert avatar_pixel[0] > 150 and avatar_pixel[1] < 80 and avatar_pixel[2] < 80


def test_build_avatar_picture_in_picture_filters_retunes_duration_and_fps():
    import roughcut.pipeline.steps as steps_mod

    filters = steps_mod._build_avatar_picture_in_picture_filters(
        base_duration=700.59,
        base_fps=29.97,
        avatar_duration=699.403,
        avatar_fps=25.0,
        overlay_width=320,
        overlay_height=320,
    )

    assert filters.startswith("scale=320:320")
    assert "setpts=PTS*" in filters
    assert "trim=duration=700.590000" in filters
    assert "settb=AVTB,framerate=fps=30000/1001:interp_start=15:interp_end=240:scene=100" in filters


@pytest.mark.asyncio
async def test_load_latest_artifact_prefers_most_recent_row(db_session):
    job_id = uuid.uuid4()
    db_session.add(
        Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
    )
    older = Artifact(
        job_id=job_id,
        artifact_type="audio_wav",
        storage_path="jobs/demo/older.wav",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(older)
    await db_session.commit()

    newer = Artifact(
        job_id=job_id,
        artifact_type="audio_wav",
        storage_path="jobs/demo/newer.wav",
        created_at=older.created_at + timedelta(seconds=1),
    )
    db_session.add(newer)
    await db_session.commit()

    artifact = await _load_latest_artifact(db_session, job_id, "audio_wav")

    assert artifact.storage_path == "jobs/demo/newer.wav"


@pytest.mark.asyncio
async def test_load_latest_timeline_prefers_most_recent_row(db_session):
    job_id = uuid.uuid4()
    db_session.add(
        Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
    )
    older = Timeline(job_id=job_id, version=1, timeline_type="editorial", data_json={"version": "older"})
    db_session.add(older)
    await db_session.commit()

    newer = Timeline(job_id=job_id, version=2, timeline_type="editorial", data_json={"version": "newer"})
    db_session.add(newer)
    await db_session.commit()

    timeline = await _load_latest_timeline(db_session, job_id, "editorial")

    assert timeline.data_json == {"version": "newer"}


@pytest.mark.asyncio
async def test_get_cover_seek_uses_latest_media_meta_when_multiple_rows_exist(db_session):
    job_id = uuid.uuid4()
    db_session.add(
        Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
    )
    db_session.add(
        Artifact(
            job_id=job_id,
            artifact_type="media_meta",
            created_at=datetime.now(timezone.utc),
            data_json={"duration": 10.0},
        )
    )
    db_session.add(
        Artifact(
            job_id=job_id,
            artifact_type="media_meta",
            created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            data_json={"duration": 250.0},
        )
    )
    await db_session.commit()

    seek = await _get_cover_seek(job_id, "unused")

    assert seek == 45.0


def test_select_cover_source_video_prefers_plain_render(tmp_path: Path):
    plain = tmp_path / "output_plain.mp4"
    packaged = tmp_path / "output.mp4"
    plain.write_bytes(b"plain")
    packaged.write_bytes(b"packaged")

    selected = _select_cover_source_video(plain, packaged)

    assert selected == plain


def test_select_cover_source_video_requires_plain_render(tmp_path: Path):
    plain = tmp_path / "output_plain.mp4"
    packaged = tmp_path / "output.mp4"
    packaged.write_bytes(b"packaged")

    with pytest.raises(FileNotFoundError, match="Plain render is required for cover extraction"):
        _select_cover_source_video(plain, packaged)


def test_select_preferred_content_profile_artifact_prefers_final_over_newer_working_copy():
    base_time = datetime(2026, 3, 12, 15, 0, tzinfo=timezone.utc)
    draft = Artifact(
        artifact_type="content_profile_draft",
        created_at=base_time,
        data_json={"kind": "draft"},
    )
    final = Artifact(
        artifact_type="content_profile_final",
        created_at=base_time + timedelta(seconds=1),
        data_json={"kind": "final"},
    )
    working_copy = Artifact(
        artifact_type="content_profile",
        created_at=base_time + timedelta(seconds=2),
        data_json={"kind": "content"},
    )

    selected = _select_preferred_content_profile_artifact([draft, final, working_copy])

    assert selected is final
