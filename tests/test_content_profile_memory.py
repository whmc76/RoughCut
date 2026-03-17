from __future__ import annotations

import uuid

import pytest

from roughcut.db.models import Job
from roughcut.review.content_profile_memory import (
    build_content_profile_memory_cloud,
    load_content_profile_user_memory,
    record_content_profile_feedback_memory,
)


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
