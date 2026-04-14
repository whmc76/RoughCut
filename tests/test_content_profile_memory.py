from __future__ import annotations

import uuid

import pytest

import roughcut.review.content_profile_memory as memory_mod
from roughcut.db.models import Job
from roughcut.review.content_profile_memory import (
    build_content_profile_memory_cloud,
    load_content_profile_user_memory,
    record_content_profile_feedback_memory,
)


async def _create_job(
    db_session,
    *,
    source_name: str,
    workflow_template: str,
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        source_path=f"E:/videos/{source_name}",
        source_name=source_name,
        status="needs_review",
        channel_profile=workflow_template,
    )
    db_session.add(job)
    await db_session.flush()
    return job


@pytest.mark.asyncio
async def test_content_profile_memory_records_corrections_and_keywords(db_session):
    job = Job(
        id=uuid.uuid4(),
        source_path="E:/videos/test.mp4",
        source_name="test.mp4",
        status="needs_review",
        channel_profile="edc_tactical",
    )
    db_session.add(job)
    await db_session.flush()

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "开箱产品",
        },
        final_profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "search_queries": ["LEATHERMAN ARC", "LEATHERMAN ARC 开箱"],
        },
        user_feedback={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "keywords": ["LEATHERMAN ARC"],
        },
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, channel_profile="edc_tactical")

    assert any(item["value"] == "LEATHERMAN" for item in memory["field_preferences"]["subject_brand"])
    assert any(item["value"] == "ARC" for item in memory["field_preferences"]["subject_model"])
    assert any(item["keyword"] == "LEATHERMAN ARC" for item in memory["keyword_preferences"])
    assert memory["recent_corrections"][0]["field_name"] in {"subject_brand", "subject_model"}
    assert any(item["phrase"] == "LEATHERMAN ARC" for item in memory["phrase_preferences"])


@pytest.mark.asyncio
async def test_content_profile_memory_records_identity_aliases_from_confirmed_review(db_session):
    job = Job(
        id=uuid.uuid4(),
        source_path="E:/videos/fxx1.mp4",
        source_name="20260316_鸿福_F叉二一小副包_开箱测评.mp4",
        status="needs_review",
        channel_profile="edc_tactical",
    )
    db_session.add(job)
    await db_session.flush()

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
        },
        final_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "identity_review": {
                "evidence_bundle": {
                    "candidate_brand": "狐蝠工业",
                    "candidate_model": "FXX1小副包",
                    "matched_glossary_aliases": {
                        "brand": ["鸿福"],
                        "model": ["F叉二一小副包"],
                    },
                }
            },
            "search_queries": ["狐蝠工业 FXX1小副包"],
        },
        user_feedback={},
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, channel_profile="edc_tactical")

    assert any(
        item["field_name"] == "subject_brand"
        and item["original_value"] == "鸿福"
        and item["corrected_value"] == "狐蝠工业"
        for item in memory["recent_corrections"]
    )
    assert any(
        item["field_name"] == "subject_model"
        and item["original_value"] == "F叉二一小副包"
        and item["corrected_value"] == "FXX1小副包"
        for item in memory["recent_corrections"]
    )


@pytest.mark.asyncio
async def test_content_profile_memory_builds_confirmed_entities_from_manual_identity_feedback(db_session):
    job = Job(
        id=uuid.uuid4(),
        source_path="E:/videos/olight.mp4",
        source_name="20260401_手电开箱.mp4",
        status="needs_review",
        channel_profile="edc_tactical",
    )
    db_session.add(job)
    await db_session.flush()

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC手电",
        },
        final_profile={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "EDC手电",
            "search_queries": ["傲雷 司令官2Ultra"],
        },
        user_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, channel_profile="edc_tactical")

    assert memory["confirmed_entities"][0]["brand"] == "傲雷"
    assert memory["confirmed_entities"][0]["model"] == "司令官2Ultra"


@pytest.mark.asyncio
async def test_content_profile_memory_learns_creative_preferences_from_manual_guidance(db_session):
    job = Job(
        id=uuid.uuid4(),
        source_path="E:/videos/commander.mp4",
        source_name="20260412_司令官2Ultra.mp4",
        status="needs_review",
        channel_profile="edc_tactical",
    )
    db_session.add(job)
    await db_session.flush()

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_type": "EDC手电",
        },
        final_profile={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "EDC手电",
            "video_theme": "司令官2Ultra版本对比与近景细节实测",
            "correction_notes": "节奏快一点，重点拍近景细节和版本差异。",
            "supplemental_context": "保留上手实测片段和最后结论。",
        },
        user_feedback={
            "correction_notes": "节奏快一点，重点拍近景细节和版本差异。",
            "supplemental_context": "保留上手实测片段和最后结论。",
        },
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, channel_profile="edc_tactical")
    tags = {str(item.get("tag") or "") for item in memory["creative_preferences"]}

    assert {"comparison_focus", "closeup_focus", "practical_demo", "fast_paced"} <= tags


@pytest.mark.asyncio
async def test_content_profile_memory_includes_confirmed_entities_when_subject_domain_is_explicit(db_session):
    job = Job(
        id=uuid.uuid4(),
        source_path="E:/videos/olight.mp4",
        source_name="20260401_手电开箱.mp4",
        status="needs_review",
        channel_profile="edc_tactical",
    )
    db_session.add(job)
    await db_session.flush()

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "EDC手电",
        },
        final_profile={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "EDC手电",
            "search_queries": ["傲雷 司令官2Ultra"],
        },
        user_feedback={
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        },
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, subject_domain="edc")

    assert any(
        item["brand"] == "傲雷" and item["model"] == "司令官2Ultra"
        for item in memory["confirmed_entities"]
    )


def test_content_profile_memory_cloud_prioritizes_specific_terms():
    cloud = build_content_profile_memory_cloud(
        {
            "field_preferences": {
                "subject_brand": [{"value": "LEATHERMAN", "count": 3}],
                "subject_model": [{"value": "ARC", "count": 2}],
            },
            "keyword_preferences": [
                {"keyword": "LEATHERMAN ARC", "count": 4},
                {"keyword": "多功能工具钳", "count": 2},
            ],
            "recent_corrections": [
                {"field_name": "subject_model", "original_value": "", "corrected_value": "ARC", "source_name": "demo.mp4"}
            ],
            "phrase_preferences": [
                {"phrase": "次顶配镜面", "count": 4},
            ],
            "style_preferences": [
                {"tag": "detail_focused", "count": 3, "example": "细节和工艺这次都拉满"},
            ],
        }
    )

    assert cloud["words"][0]["label"] in {"LEATHERMAN", "LEATHERMAN ARC"}
    assert any(item["label"] == "ARC" and item["kind"] == "subject_model" for item in cloud["words"])
    assert cloud["recent_corrections"][0]["corrected_value"] == "ARC"
    assert any(item["label"] == "次顶配镜面" and item["kind"] == "phrase" for item in cloud["words"])
    assert cloud["phrases"][0]["phrase"] == "次顶配镜面"
    assert cloud["styles"][0]["tag"] == "detail_focused"


@pytest.mark.asyncio
async def test_content_profile_memory_isolates_graph_memory_by_subject_domain(db_session):
    edc_job = await _create_job(
        db_session,
        source_name="20260401_鸿福_F叉二一小副包_开箱测评.mp4",
        workflow_template="edc_tactical",
    )
    food_job = await _create_job(
        db_session,
        source_name="20260401_老韩_爆汁牛肉堡_探店.mp4",
        workflow_template="food_explore",
    )

    await record_content_profile_feedback_memory(
        db_session,
        job=edc_job,
        draft_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
        },
        final_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "identity_review": {
                "evidence_bundle": {
                    "candidate_brand": "狐蝠工业",
                    "candidate_model": "FXX1小副包",
                    "matched_glossary_aliases": {
                        "brand": ["鸿福"],
                        "model": ["F叉二一小副包"],
                    },
                }
            },
        },
        user_feedback={},
    )
    await record_content_profile_feedback_memory(
        db_session,
        job=food_job,
        draft_profile={
            "subject_brand": "老韩",
            "subject_model": "爆汁牛肉堡",
            "subject_type": "探店试吃",
        },
        final_profile={
            "subject_brand": "老韩",
            "subject_model": "爆汁牛肉堡",
            "subject_type": "探店试吃",
            "identity_review": {
                "evidence_bundle": {
                    "candidate_brand": "老韩",
                    "candidate_model": "爆汁牛肉堡",
                    "matched_glossary_aliases": {
                        "brand": ["韩叔"],
                        "model": ["牛堡"],
                    },
                }
            },
        },
        user_feedback={},
    )
    await db_session.flush()

    edc_memory = await load_content_profile_user_memory(db_session, subject_domain="edc")
    food_memory = await load_content_profile_user_memory(db_session, subject_domain="food")

    assert any(
        item["brand"] == "狐蝠工业"
        and item["model"] == "FXX1小副包"
        and "F叉二一小副包" in item["model_aliases"]
        for item in edc_memory["confirmed_entities"]
    )
    assert not any(item["brand"] == "老韩" for item in edc_memory["confirmed_entities"])
    assert any(
        item["brand"] == "老韩"
        and item["model"] == "爆汁牛肉堡"
        and "牛堡" in item["model_aliases"]
        for item in food_memory["confirmed_entities"]
    )
    assert not any(item["brand"] == "狐蝠工业" for item in food_memory["confirmed_entities"])


@pytest.mark.asyncio
async def test_content_profile_memory_promotes_identity_aliases_into_confirmed_entities(db_session):
    job = await _create_job(
        db_session,
        source_name="20260316_鸿福_F叉二一小副包_开箱测评.mp4",
        workflow_template="edc_tactical",
    )

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
        },
        final_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "identity_review": {
                "evidence_bundle": {
                    "candidate_brand": "狐蝠工业",
                    "candidate_model": "FXX1小副包",
                    "matched_glossary_aliases": {
                        "brand": ["鸿福"],
                        "model": ["F叉二一小副包"],
                    },
                }
            },
        },
        user_feedback={},
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, subject_domain="edc")

    assert any(
        item["brand"] == "狐蝠工业"
        and item["model"] == "FXX1小副包"
        and "F叉二一小副包" in item["model_aliases"]
        and any("鸿福" in phrase for phrase in item["phrases"])
        for item in memory["confirmed_entities"]
    )


@pytest.mark.asyncio
async def test_content_profile_memory_learns_reusable_aliases_from_review_notes(db_session, monkeypatch: pytest.MonkeyPatch):
    class _FakeResponse:
        def as_json(self):
            return {
                "aliases": [
                    {
                        "field_name": "subject_brand",
                        "alias_value": "赫斯郡",
                        "canonical_value": "HSJUN",
                        "confidence": 0.96,
                        "reason": "审核备注明确给出同音品牌修正",
                    },
                    {
                        "field_name": "subject_model",
                        "alias_value": "游任",
                        "canonical_value": "游刃",
                        "confidence": 0.91,
                        "reason": "审核备注指出新品名误听",
                    },
                ]
            }

    class _FakeProvider:
        async def complete(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(memory_mod, "get_reasoning_provider", lambda: _FakeProvider())

    job = await _create_job(
        db_session,
        source_name="20260404_hsjun_boltboat_you ren.mp4",
        workflow_template="unboxing_standard",
    )

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_type": "户外徒步背包",
            "subject_domain": "functional",
        },
        final_profile={
            "subject_brand": "HSJUN",
            "subject_model": "游刃",
            "subject_type": "户外徒步背包",
            "subject_domain": "functional",
            "search_queries": ["HSJUN 游刃", "HSJUN 游刃 背包"],
        },
        user_feedback={
            "correction_notes": "赫斯郡其实就是 HSJUN，这期新品叫游刃，不是游任。",
        },
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, subject_domain="functional")

    assert any(
        item["brand"] == "HSJUN"
        and item["model"] == "游刃"
        and "赫斯郡" in item.get("brand_aliases", [])
        and "游任" in item.get("model_aliases", [])
        for item in memory["confirmed_entities"]
    )
    assert any(
        item["field_name"] == "subject_brand"
        and item["original_value"] == "赫斯郡"
        and item["corrected_value"] == "HSJUN"
        for item in memory["recent_corrections"]
    )
    assert any(
        item["field_name"] == "subject_model"
        and item["original_value"] == "游任"
        and item["corrected_value"] == "游刃"
        for item in memory["recent_corrections"]
    )


@pytest.mark.asyncio
async def test_content_profile_memory_learned_review_aliases_stay_within_subject_domain(db_session, monkeypatch: pytest.MonkeyPatch):
    class _FakeResponse:
        def as_json(self):
            return {
                "aliases": [
                    {
                        "field_name": "subject_brand",
                        "alias_value": "赫斯俊",
                        "canonical_value": "HSJUN",
                        "confidence": 0.94,
                        "reason": "品牌同音误听",
                    }
                ]
            }

    class _FakeProvider:
        async def complete(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(memory_mod, "get_reasoning_provider", lambda: _FakeProvider())

    job = await _create_job(
        db_session,
        source_name="20260404_hsjun.mp4",
        workflow_template="unboxing_standard",
    )

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_type": "户外徒步背包",
            "subject_domain": "functional",
        },
        final_profile={
            "subject_brand": "HSJUN",
            "subject_model": "游刃",
            "subject_type": "户外徒步背包",
            "subject_domain": "functional",
        },
        user_feedback={
            "supplemental_context": "赫斯俊就是 HSJUN。",
        },
    )
    await db_session.flush()

    bag_memory = await load_content_profile_user_memory(db_session, subject_domain="functional")
    edc_memory = await load_content_profile_user_memory(db_session, subject_domain="edc")

    assert any(
        item["brand"] == "HSJUN" and "赫斯俊" in item.get("brand_aliases", [])
        for item in bag_memory["confirmed_entities"]
    )
    assert not any(
        item["brand"] == "HSJUN"
        for item in edc_memory.get("confirmed_entities", [])
    )


@pytest.mark.asyncio
async def test_content_profile_memory_suppresses_rejected_alias_mappings(db_session):
    confirmed_job = await _create_job(
        db_session,
        source_name="20260316_鸿福_F叉二一小副包_开箱测评.mp4",
        workflow_template="edc_tactical",
    )
    rejected_job = await _create_job(
        db_session,
        source_name="20260402_鸿福_F叉二一小副包_纠错.mp4",
        workflow_template="edc_tactical",
    )

    await record_content_profile_feedback_memory(
        db_session,
        job=confirmed_job,
        draft_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
        },
        final_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "identity_review": {
                "evidence_bundle": {
                    "candidate_brand": "狐蝠工业",
                    "candidate_model": "FXX1小副包",
                    "matched_glossary_aliases": {
                        "brand": ["鸿福"],
                        "model": ["F叉二一小副包"],
                    },
                }
            },
        },
        user_feedback={},
    )
    await record_content_profile_feedback_memory(
        db_session,
        job=rejected_job,
        draft_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
        },
        final_profile={
            "subject_brand": "狐锋工业",
            "subject_model": "FXX1小副包 Pro",
            "identity_review": {
                "evidence_bundle": {
                    "candidate_brand": "狐蝠工业",
                    "candidate_model": "FXX1小副包",
                    "matched_glossary_aliases": {
                        "brand": ["鸿福"],
                        "model": ["F叉二一小副包"],
                    },
                }
            },
        },
        user_feedback={
            "subject_brand": "狐锋工业",
            "subject_model": "FXX1小副包 Pro",
        },
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, subject_domain="edc")

    assert not any(
        item["field_name"] == "subject_brand"
        and item["original_value"] == "鸿福"
        and item["corrected_value"] == "狐蝠工业"
        for item in memory["recent_corrections"]
    )
    assert not any(
        item["field_name"] == "subject_model"
        and item["original_value"] == "F叉二一小副包"
        and item["corrected_value"] == "FXX1小副包"
        for item in memory["recent_corrections"]
    )


@pytest.mark.asyncio
async def test_content_profile_memory_falls_back_to_legacy_corrections_when_graph_is_empty(db_session):
    job = await _create_job(
        db_session,
        source_name="legacy.mp4",
        workflow_template="edc_tactical",
    )
    del job

    from roughcut.db.models import ContentProfileCorrection

    db_session.add(
        ContentProfileCorrection(
            job_id=uuid.uuid4(),
            source_name="legacy.mp4",
            subject_domain="edc",
            field_name="subject_brand",
            original_value="莱泽曼",
            corrected_value="LEATHERMAN",
        )
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, subject_domain="edc")

    assert any(item["value"] == "LEATHERMAN" for item in memory["field_preferences"]["subject_brand"])
    assert any(
        item["field_name"] == "subject_brand"
        and item["original_value"] == "莱泽曼"
        and item["corrected_value"] == "LEATHERMAN"
        for item in memory["recent_corrections"]
    )


@pytest.mark.asyncio
async def test_content_profile_memory_does_not_learn_conflicting_comparison_model_as_alias(db_session):
    job = await _create_job(
        db_session,
        source_name="nitecore-edc17-vs-edc37.mp4",
        workflow_template="edc_tactical",
    )

    await record_content_profile_feedback_memory(
        db_session,
        job=job,
        draft_profile={
            "subject_domain": "电子产品",
            "subject_model": "EDC37",
        },
        final_profile={
            "subject_domain": "电子产品",
            "subject_model": "EDC17",
        },
        user_feedback={
            "subject_model": "EDC17",
        },
    )
    await db_session.flush()

    memory = await load_content_profile_user_memory(db_session, subject_domain="edc")

    assert not any(
        item["field_name"] == "subject_model"
        and item["original_value"] == "EDC37"
        and item["corrected_value"] == "EDC17"
        for item in memory.get("recent_corrections") or []
    )
