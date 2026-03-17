from __future__ import annotations

import uuid

import pytest

from roughcut.db.models import GlossaryTerm, SubtitleCorrection, SubtitleItem
from roughcut.review.glossary_engine import (
    apply_corrections_to_text,
    apply_glossary_corrections,
    assess_glossary_correction_automation,
)


def _mock_correction(original: str, suggested: str, applied: bool = True, decision: str = "accepted"):
    return SubtitleCorrection(
        original_span=original,
        suggested_span=suggested,
        change_type="glossary",
        confidence=1.0,
        auto_applied=applied,
        human_decision=decision,
        human_override=None,
    )


def test_apply_corrections_basic():
    text = "这款GPT4模型效果很好"
    corrections = [_mock_correction("GPT4", "GPT-4")]
    result = apply_corrections_to_text(text, corrections)
    assert result == "这款GPT-4模型效果很好"


def test_apply_corrections_with_override():
    text = "这款GPT4模型效果很好"
    c = _mock_correction("GPT4", "GPT-4")
    c.human_override = "GPT-4o"
    result = apply_corrections_to_text(text, [c])
    assert result == "这款GPT-4o模型效果很好"


def test_apply_corrections_pending_not_applied():
    text = "这款GPT4模型效果很好"
    c = _mock_correction("GPT4", "GPT-4", applied=False, decision="pending")
    result = apply_corrections_to_text(text, [c])
    assert result == text  # Not applied


def test_apply_corrections_rejected_not_applied():
    text = "这款GPT4模型效果很好"
    c = _mock_correction("GPT4", "GPT-4", applied=False, decision="rejected")
    result = apply_corrections_to_text(text, [c])
    assert result == text


def test_assess_glossary_correction_automation_accepts_safe_token_match():
    assessment = assess_glossary_correction_automation(
        full_text="这款 GPT4 模型效果很好",
        original_span="GPT4",
        suggested_span="GPT-4",
        match_start=3,
        match_end=7,
        confidence=0.95,
    )

    assert assessment["auto_apply"] is True
    assert assessment["score"] >= 0.9


def test_assess_glossary_correction_automation_blocks_embedded_english_match():
    assessment = assess_glossary_correction_automation(
        full_text="capromax",
        original_span="pro",
        suggested_span="Pro",
        match_start=4,
        match_end=7,
        confidence=0.95,
    )

    assert assessment["auto_apply"] is False
    assert "匹配落在更长英文词内部" in assessment["blocking_reasons"]


@pytest.mark.asyncio
async def test_apply_glossary_corrections_auto_accepts_safe_matches(db_session, monkeypatch):
    import roughcut.review.glossary_engine as glossary_engine_module

    settings = type(
        "SettingsStub",
        (),
        {
            "auto_accept_glossary_corrections": True,
            "glossary_correction_review_threshold": 0.9,
        },
    )()
    monkeypatch.setattr(glossary_engine_module, "get_settings", lambda: settings)

    subtitle_item = SubtitleItem(
        job_id=uuid.uuid4(),
        version=1,
        item_index=0,
        start_time=0.0,
        end_time=1.0,
        text_raw="这款 GPT4 模型效果很好",
        text_norm="这款 GPT4 模型效果很好",
        text_final=None,
    )
    db_session.add(subtitle_item)
    db_session.add(
        GlossaryTerm(
            correct_form="GPT-4",
            wrong_forms=["GPT4"],
            category="model",
        )
    )
    await db_session.flush()

    corrections = await apply_glossary_corrections(subtitle_item.job_id, [subtitle_item], db_session)

    assert len(corrections) == 1
    assert corrections[0].auto_applied is True
    assert corrections[0].human_decision == "accepted"


@pytest.mark.asyncio
async def test_apply_glossary_corrections_accepts_builtin_dict_terms(db_session, monkeypatch):
    import roughcut.review.glossary_engine as glossary_engine_module

    settings = type(
        "SettingsStub",
        (),
        {
            "auto_accept_glossary_corrections": True,
            "glossary_correction_review_threshold": 0.9,
        },
    )()
    monkeypatch.setattr(glossary_engine_module, "get_settings", lambda: settings)

    subtitle_item = SubtitleItem(
        job_id=uuid.uuid4(),
        version=1,
        item_index=0,
        start_time=0.0,
        end_time=1.0,
        text_raw="这个键变效果和提词都要再调一下",
        text_norm="这个键变效果和提词都要再调一下",
        text_final=None,
    )
    db_session.add(subtitle_item)
    await db_session.flush()

    corrections = await apply_glossary_corrections(
        subtitle_item.job_id,
        [subtitle_item],
        db_session,
        glossary_terms=[
            {"correct_form": "渐变", "wrong_forms": ["键变"]},
            {"correct_form": "提示词", "wrong_forms": ["提词"]},
        ],
    )

    assert len(corrections) == 2
    assert all(item.auto_applied for item in corrections)


@pytest.mark.asyncio
async def test_apply_glossary_corrections_brand_terms_require_review(db_session, monkeypatch):
    import roughcut.review.glossary_engine as glossary_engine_module

    settings = type(
        "SettingsStub",
        (),
        {
            "auto_accept_glossary_corrections": True,
            "glossary_correction_review_threshold": 0.9,
        },
    )()
    monkeypatch.setattr(glossary_engine_module, "get_settings", lambda: settings)

    subtitle_item = SubtitleItem(
        job_id=uuid.uuid4(),
        version=1,
        item_index=0,
        start_time=0.0,
        end_time=1.0,
        text_raw="这个傲雷的小手电我之前也玩过",
        text_norm="这个傲雷的小手电我之前也玩过",
        text_final=None,
    )
    db_session.add(subtitle_item)
    await db_session.flush()

    corrections = await apply_glossary_corrections(
        subtitle_item.job_id,
        [subtitle_item],
        db_session,
        glossary_terms=[
            {"correct_form": "OLIGHT", "wrong_forms": ["傲雷"], "category": "edc_brand"},
        ],
    )

    assert len(corrections) == 1
    assert corrections[0].auto_applied is False
    assert corrections[0].human_decision == "pending"
