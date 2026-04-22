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
from roughcut.review.subtitle_memory import build_subtitle_review_memory, build_transcription_prompt


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
    )

    hotwords = extract_prompt_hotwords(prompt)
    assert "MT34" in hotwords[:3]
    assert "NOC折刀" in hotwords[:4]
    assert len(hotwords) <= 12
    assert len(prompt) <= 320
