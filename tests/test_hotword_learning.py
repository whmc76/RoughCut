import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.db.models import Job
from roughcut.db.session import Base
from roughcut.review.hotword_learning import (
    extract_prompt_hotwords,
    load_learned_hotwords,
    record_prompted_hotwords,
    record_learned_hotwords_from_content_profile_feedback,
)
from roughcut.pipeline.steps import _build_effective_glossary_terms, _infer_subject_domain_for_memory
from roughcut.review.subtitle_memory import build_subtitle_review_memory, build_transcription_prompt, resolve_transcription_category_scope


@pytest.mark.asyncio
async def test_records_and_loads_learned_hotwords_from_profile_feedback() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(source_path="source.mp4", source_name="source.mp4", status="processing", workflow_template="edc_tactical")
            session.add(job)
            await session.flush()

            await record_learned_hotwords_from_content_profile_feedback(
                session,
                job=job,
                final_profile={
                    "subject_domain": "edc",
                    "subject_brand": "NOC",
                    "subject_model": "MT34",
                    "subject_type": "折刀",
                    "search_queries": ["NOC MT34", "DLC折刀"],
                },
                user_feedback={"keywords": ["MT34", "NOC折刀"]},
                subject_domain="edc",
            )
            await session.commit()

            learned = await load_learned_hotwords(session, subject_domain="edc")
            await record_prompted_hotwords(session, prompt_hotwords=["MT34", "NOC折刀"])
            await session.commit()
            prompted = await load_learned_hotwords(session, subject_domain="edc")
    finally:
        await engine.dispose()

    terms = {item["term"] for item in learned}
    assert {"NOC", "MT34", "折刀", "NOC折刀"}.issubset(terms)
    assert all(item["score"] > 0 for item in learned)
    prompted_counts = {item["canonical_form"]: item for item in prompted}
    assert prompted_counts["MT34"]["prompt_count"] >= 1


def test_learned_hotwords_are_prioritized_in_transcription_prompt() -> None:
    review_memory = build_subtitle_review_memory(
        workflow_template="unboxing_standard",
        subject_domain="edc",
        source_name="VID_MT34.mp4",
        glossary_terms=[],
        user_memory={
            "learned_hotwords": [
                {"term": "MT34", "canonical_form": "MT34", "positive_count": 4, "confidence": 0.95},
                {"term": "NOC折刀", "canonical_form": "NOC折刀", "positive_count": 3, "confidence": 0.9},
            ],
        },
        recent_subtitles=[],
        content_profile={"subject_domain": "edc", "subject_type": "折刀"},
        include_recent_terms=False,
        include_recent_examples=False,
    )
    prompt = build_transcription_prompt(
        source_name="VID_MT34.mp4",
        workflow_template="unboxing_standard",
        review_memory=review_memory,
        dialect_profile="mandarin",
        content_profile={"subject_type": "折刀"},
    )

    hotwords = extract_prompt_hotwords(prompt)
    assert "MT34" in hotwords[:3]
    assert "NOC折刀" in hotwords[:4]
    assert len(hotwords) <= 12
    assert len(prompt) <= 320


def test_transcription_prompt_filters_cross_scope_terms_for_flashlight() -> None:
    review_memory = {
        "subject_domain": "edc",
        "terms": [
            {"term": "OLIGHT", "count": 9, "domain": "flashlight", "category_scope": "flashlight"},
            {"term": "掠夺者2 mini", "count": 8, "domain": "flashlight", "category_scope": "flashlight"},
            {"term": "BOLTBOAT", "count": 10, "domain": "bag", "category_scope": "bag"},
            {"term": "NOC MT34", "count": 10, "domain": "knife", "category_scope": "knife"},
        ],
        "transcription_seed_term_details": [
            {"term": "OLIGHT", "domain": "flashlight", "category_scope": "flashlight"},
            {"term": "掠夺者2 mini", "domain": "flashlight", "category_scope": "flashlight"},
            {"term": "BOLTBOAT", "domain": "bag", "category_scope": "bag"},
        ],
        "learned_hotwords": [
            {"term": "OLIGHT", "canonical_form": "OLIGHT", "subject_domain": "flashlight"},
            {"term": "BOLTBOAT", "canonical_form": "BOLTBOAT", "subject_domain": "bag"},
        ],
        "aliases": [
            {"wrong": "傲雷", "correct": "OLIGHT"},
            {"wrong": "船包", "correct": "BOLTBOAT"},
        ],
    }

    prompt = build_transcription_prompt(
        source_name="傲雷掠夺者2 mini 手电开箱.mp4",
        workflow_template="unboxing_standard",
        review_memory=review_memory,
        dialect_profile="mandarin",
        content_profile={"subject_type": "手电"},
    )

    hotwords = extract_prompt_hotwords(prompt)
    assert "掠夺者2 mini" in hotwords
    assert "傲雷=OLIGHT" in prompt
    assert "BOLTBOAT" not in hotwords
    assert "NOC MT34" not in hotwords
    assert "船包=BOLTBOAT" not in prompt


def test_ingestible_edc_style_source_does_not_prompt_knife_hotwords() -> None:
    source_name = "IMG_0024 luckykiss edc弹射舱 益生菌含片.MOV"
    content_profile: dict = {}
    subject_domain = _infer_subject_domain_for_memory(
        workflow_template="edc_tactical",
        content_profile=content_profile,
        source_name=source_name,
    )
    effective_terms = _build_effective_glossary_terms(
        glossary_terms=[],
        workflow_template="edc_tactical",
        content_profile=content_profile,
        source_name=source_name,
        subject_domain=subject_domain,
    )
    review_memory = build_subtitle_review_memory(
        workflow_template="edc_tactical",
        subject_domain=subject_domain,
        source_name=source_name,
        glossary_terms=effective_terms,
        user_memory={},
        recent_subtitles=[],
        content_profile=content_profile,
        include_recent_terms=False,
        include_recent_examples=False,
    )
    prompt = build_transcription_prompt(
        source_name=source_name,
        workflow_template="edc_tactical",
        review_memory=review_memory,
        dialect_profile="mandarin",
        content_profile=content_profile,
    )

    hotwords = extract_prompt_hotwords(prompt)
    forbidden_terms = {"NOC", "REATE", "LEATHERMAN", "OLIGHT", "BOLTBOAT", "HSJUN", "折刀", "工具钳"}
    assert subject_domain == "food"
    assert resolve_transcription_category_scope(
        review_memory,
        workflow_template="edc_tactical",
        source_name=source_name,
        content_profile=content_profile,
    ) == "food"
    assert not review_memory.get("transcription_seed_term_details")
    assert any("益生" in word for word in hotwords)
    assert not (set(hotwords) & forbidden_terms)
    assert "折刀" not in prompt


def test_flashlight_source_name_overrides_generic_edc_knife_memory() -> None:
    source_name = "merged_3_傲雷掠夺者2mini战术手电开箱.mp4"
    subject_domain = _infer_subject_domain_for_memory(
        workflow_template="edc_tactical",
        content_profile={},
        source_name=source_name,
    )
    effective_terms = _build_effective_glossary_terms(
        glossary_terms=[],
        workflow_template="edc_tactical",
        content_profile={},
        source_name=source_name,
        subject_domain=subject_domain,
    )
    review_memory = build_subtitle_review_memory(
        workflow_template="edc_tactical",
        subject_domain=subject_domain,
        source_name=source_name,
        glossary_terms=effective_terms,
        user_memory={
            "learned_hotwords": [
                {"term": "NOC MT34折刀", "canonical_form": "NOC MT34折刀", "subject_domain": "edc"},
                {"term": "REATE EDC折刀", "canonical_form": "REATE EDC折刀", "subject_domain": "edc"},
            ],
        },
        recent_subtitles=[],
        content_profile={},
        include_recent_terms=False,
        include_recent_examples=False,
    )
    prompt = build_transcription_prompt(
        source_name=source_name,
        workflow_template="edc_tactical",
        review_memory=review_memory,
        dialect_profile="mandarin",
        content_profile={},
    )

    hotwords = extract_prompt_hotwords(prompt)
    assert subject_domain == "edc"
    assert resolve_transcription_category_scope(
        review_memory,
        workflow_template="edc_tactical",
        source_name=source_name,
        content_profile={},
    ) == "flashlight"
    assert "OLIGHT" in hotwords or "傲雷" in prompt
    assert "NOC" not in prompt
    assert "REATE" not in prompt
    assert "折刀" not in prompt
