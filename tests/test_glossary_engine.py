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


def test_assess_glossary_correction_automation_accepts_low_risk_brand_normalization():
    full_text = "这次我把 Loop Gear 的两款小灯放一起看"
    start = full_text.index("Loop Gear")
    assessment = assess_glossary_correction_automation(
        full_text=full_text,
        original_span="Loop Gear",
        suggested_span="LOOPGEAR",
        match_start=start,
        match_end=start + len("Loop Gear"),
        confidence=0.95,
        auto_accept_enabled=True,
    )

    assert assessment["auto_apply"] is True
    assert assessment["blocking_reasons"] == []


def test_api_glossary_sanitize_wrong_forms_filters_conflicting_model_aliases():
    from roughcut.api.glossary import _sanitize_glossary_wrong_forms

    assert _sanitize_glossary_wrong_forms("EDC17", ["EDC37", "EDC幺七", "EDC幺七"]) == ["EDC幺七"]


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
async def test_apply_glossary_corrections_skips_conflicting_model_aliases(db_session, monkeypatch):
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
        text_raw="我之前一直用的是EDC37。",
        text_norm="我之前一直用的是EDC37。",
        text_final=None,
    )
    db_session.add(subtitle_item)
    db_session.add(
        GlossaryTerm(
            correct_form="EDC17",
            wrong_forms=["EDC37", "EDC幺七"],
            category="model",
        )
    )
    await db_session.flush()

    corrections = await apply_glossary_corrections(subtitle_item.job_id, [subtitle_item], db_session)

    assert corrections == []


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


@pytest.mark.asyncio
async def test_apply_glossary_corrections_auto_accepts_profile_confirmed_brand_alias(db_session, monkeypatch):
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
        text_raw="纳拓这个工具我最近一直在包里放着",
        text_norm="纳拓这个工具我最近一直在包里放着",
        text_final=None,
    )
    db_session.add(subtitle_item)
    await db_session.flush()

    corrections = await apply_glossary_corrections(
        subtitle_item.job_id,
        [subtitle_item],
        db_session,
        glossary_terms=[
            {"correct_form": "NexTool", "wrong_forms": ["纳拓"], "category": "brand"},
        ],
        content_profile={"subject_brand": "NexTool", "subject_model": "S11PRO"},
    )

    assert len(corrections) == 1
    assert corrections[0].auto_applied is True
    assert corrections[0].human_decision == "accepted"


@pytest.mark.asyncio
async def test_apply_glossary_corrections_auto_accepts_low_risk_brand_normalization(db_session, monkeypatch):
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
        text_raw="这次我把 Loop Gear 的两款小灯放一起看",
        text_norm="这次我把 Loop Gear 的两款小灯放一起看",
        text_final=None,
    )
    db_session.add(subtitle_item)
    await db_session.flush()

    corrections = await apply_glossary_corrections(
        subtitle_item.job_id,
        [subtitle_item],
        db_session,
        glossary_terms=[
            {"correct_form": "LOOPGEAR", "wrong_forms": ["Loop Gear"], "category": "flashlight_brand"},
        ],
    )

    assert len(corrections) == 1
    assert corrections[0].auto_applied is True
    assert corrections[0].human_decision == "accepted"


@pytest.mark.asyncio
async def test_apply_glossary_corrections_filters_brand_expansion_noise(db_session, monkeypatch):
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
        text_raw="PSIGEAR 和狐蝠工业的配件都在这。",
        text_norm="PSIGEAR 和狐蝠工业的配件都在这。",
        text_final=None,
    )
    db_session.add(subtitle_item)
    await db_session.flush()

    corrections = await apply_glossary_corrections(
        subtitle_item.job_id,
        [subtitle_item],
        db_session,
        glossary_terms=[
            {"correct_form": "狐蝠工业", "wrong_forms": ["PSIGEAR", "狐蝠"], "category": "bag_brand"},
            {"correct_form": "FOXBAT狐蝠工业", "wrong_forms": ["狐蝠工业"], "category": "bag_brand"},
            {"correct_form": "狐蝠工业 FOXBAT", "wrong_forms": ["狐蝠工业"], "category": "bag_brand"},
        ],
        content_profile={"subject_brand": "狐蝠工业", "subject_model": "阵风", "subject_type": "EDC机能包"},
    )

    assert corrections == []


@pytest.mark.asyncio
async def test_apply_glossary_corrections_skips_candidate_when_suggested_form_already_present(db_session, monkeypatch):
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
        text_raw="这是狐蝠工业 HSJUN x BOLTBOAT 联名的阵风。",
        text_norm="这是狐蝠工业 HSJUN x BOLTBOAT 联名的阵风。",
        text_final=None,
    )
    db_session.add(subtitle_item)
    await db_session.flush()

    corrections = await apply_glossary_corrections(
        subtitle_item.job_id,
        [subtitle_item],
        db_session,
        glossary_terms=[
            {"correct_form": "HSJUN x BOLTBOAT", "wrong_forms": ["狐蝠工业"], "category": "brand"},
        ],
    )

    assert corrections == []


@pytest.mark.asyncio
async def test_apply_glossary_corrections_filters_cross_brand_noise_with_source_constraints(db_session, monkeypatch):
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
        text_raw="PSIGEAR 的压缩水壶套很能装。",
        text_norm="PSIGEAR 的压缩水壶套很能装。",
        text_final=None,
    )
    db_session.add(subtitle_item)
    await db_session.flush()

    corrections = await apply_glossary_corrections(
        subtitle_item.job_id,
        [subtitle_item],
        db_session,
        glossary_terms=[
            {"correct_form": "狐蝠工业", "wrong_forms": ["PSIGEAR"], "category": "source_identity"},
        ],
        content_profile={"subject_brand": "狐蝠工业", "subject_model": "阵风", "subject_type": "EDC机能包"},
    )

    assert corrections == []
