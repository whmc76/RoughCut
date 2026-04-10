from __future__ import annotations

import pytest

from roughcut.review.content_understanding_retrieval import search_confirmed_content_entities
from roughcut.review.entity_graph import add_entity_aliases, upsert_content_profile_entity


@pytest.mark.asyncio
async def test_search_confirmed_content_entities_builds_strong_entity_candidate_from_graph_and_aliases(db_session):
    entity = await upsert_content_profile_entity(
        db_session,
        subject_domain="bag",
        brand="狐蝠工业",
        model="FXX1小副包",
        subject_type="机能副包",
        source_name="20260316_鸿福_F叉二一小副包_开箱测评.mp4",
    )
    await add_entity_aliases(db_session, entity=entity, field_name="subject_brand", aliases=["鸿福"])
    await add_entity_aliases(db_session, entity=entity, field_name="subject_model", aliases=["F叉二一小副包"])
    await db_session.flush()

    results = await search_confirmed_content_entities(
        db_session,
        search_queries=["鸿福 F叉二一小副包 开箱"],
        subject_domain="bag",
        evidence_texts=["这期鸿福 F叉二一小副包做个开箱测评，重点看分仓和挂点。"],
    )

    assert results
    best = results[0]
    assert best["brand"] == "狐蝠工业"
    assert best["model"] == "FXX1小副包"
    assert "鸿福" in best["matched_aliases"]["brand"]
    assert "F叉二一小副包" in best["matched_aliases"]["model"]
    assert best["evidence_strength"] in {"moderate", "strong"}
    assert best["support_score"] >= 0.48


@pytest.mark.asyncio
async def test_search_confirmed_content_entities_can_build_glossary_only_candidate_without_graph_hit(db_session):
    results = await search_confirmed_content_entities(
        db_session,
        search_queries=["鸿福 F叉二一小副包"],
        subject_domain="bag",
        evidence_texts=["这期鸿福 F叉二一小副包做个开箱测评。"],
    )

    assert results
    assert any(
        item["brand"] == "狐蝠工业"
        and item["model"] in {"FXX1小副包", "FXX1"}
        and item["source_type"] == "glossary_entity_candidate"
        for item in results
    )


@pytest.mark.asyncio
async def test_search_confirmed_content_entities_surfaces_builtin_entity_catalog_candidate(db_session):
    results = await search_confirmed_content_entities(
        db_session,
        search_queries=["LEATHERMAN ARC 开箱"],
        subject_domain="tools",
        evidence_texts=["这把莱德曼 ASC 工具钳主要看单手开合和钳口细节。"],
    )

    assert results
    assert any(
        item["brand"] == "LEATHERMAN"
        and item["model"] == "ARC"
        and item["source_type"] == "builtin_entity_catalog"
        and "ASC" in list((item.get("matched_aliases") or {}).get("model") or [])
        and "supporting_keyword" in list(item.get("matched_fields") or [])
        for item in results
    )


@pytest.mark.asyncio
async def test_search_confirmed_content_entities_enriches_graph_candidate_with_cn_brand_aliases(db_session):
    await upsert_content_profile_entity(
        db_session,
        subject_domain="knife",
        brand="REATE",
        model="EXO",
        subject_type="EDC折刀",
        source_name="20260411_reate_exo.mp4",
    )
    await db_session.flush()

    results = await search_confirmed_content_entities(
        db_session,
        search_queries=["锐特"],
        subject_domain="knife",
        evidence_texts=[],
    )

    assert results
    best = results[0]
    assert best["brand"] == "REATE"
    assert best["brand_cn"] == "锐特"
    assert best["brand_bilingual"] == "锐特REATE"
    assert "锐特" in list((best.get("matched_aliases") or {}).get("brand") or [])


@pytest.mark.asyncio
async def test_search_confirmed_content_entities_enriches_memory_candidate_with_localized_brand_display(db_session):
    results = await search_confirmed_content_entities(
        db_session,
        search_queries=["锐特"],
        subject_domain="knife",
        confirmed_entities=[
            {
                "brand": "REATE",
                "model": "EXO",
                "subject_type": "EDC折刀",
                "phrases": [],
                "brand_aliases": [],
            }
        ],
        evidence_texts=[],
    )

    assert results
    best = results[0]
    assert best["brand"] == "REATE"
    assert best["brand_cn"] == "锐特"
    assert best["brand_bilingual"] == "锐特REATE"
    assert "锐特" in list((best.get("matched_aliases") or {}).get("brand") or [])
