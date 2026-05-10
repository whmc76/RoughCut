from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.config import get_settings
from roughcut.db.models import GlossaryTerm, SubtitleCorrection, SubtitleItem
from roughcut.review.model_identity import (
    filter_conflicting_model_wrong_forms as _shared_filter_conflicting_model_wrong_forms,
    model_numbers_conflict,
)
from roughcut.review.subtitle_term_resolution import _should_ignore_patch_candidate
from roughcut.review.text_rewrite_policy import disabled_correction_candidates, disabled_text_rewrite


@dataclass
class CorrectionSuggestion:
    subtitle_item_id: uuid.UUID
    original_span: str
    suggested_span: str
    change_type: str
    confidence: float
    source: str


def assess_glossary_correction_automation(
    *,
    full_text: str,
    original_span: str,
    suggested_span: str,
    match_start: int,
    match_end: int,
    confidence: float,
    auto_accept_enabled: bool = True,
    threshold: float = 0.9,
) -> dict[str, object]:
    normalized_threshold = max(0.0, min(1.0, float(threshold)))
    score = max(0.0, min(1.0, float(confidence)))
    reasons: list[str] = []
    review_reasons: list[str] = []
    blocking_reasons: list[str] = []

    original = str(original_span or "").strip()
    suggested = str(suggested_span or "").strip()
    text = str(full_text or "")

    if not original or not suggested:
        blocking_reasons.append("术语候选缺少原文或修正值")
    elif model_numbers_conflict(original, suggested):
        blocking_reasons.append("型号数字冲突，不能自动改写相邻型号")
    else:
        length_ratio = len(suggested) / max(len(original), 1)
        if 0.6 <= length_ratio <= 1.8:
            score += 0.02
            reasons.append("替换长度变化可控")
        else:
            review_reasons.append("替换长度变化偏大")

        if _contains_cjk(original) or _contains_cjk(suggested):
            if len(_compact_text(original)) >= 2 and len(_compact_text(suggested)) >= 2:
                score += 0.03
                reasons.append("中文术语匹配稳定")
            else:
                review_reasons.append("中文术语过短")
        else:
            if len(_compact_text(original)) >= 3:
                score += 0.02
                reasons.append("英文术语长度足够")
            else:
                blocking_reasons.append("英文术语过短")

            if _has_token_boundaries(text, match_start, match_end):
                score += 0.05
                reasons.append("匹配位于独立英文 token")
            else:
                blocking_reasons.append("匹配落在更长英文词内部")
        if _is_low_risk_brand_normalization(original, suggested):
            score += 0.04
            reasons.append("品牌名仅做大小写/空格归一")

    score = round(min(score, 0.99), 3)
    auto_apply = auto_accept_enabled and score >= normalized_threshold and not blocking_reasons
    return {
        "enabled": auto_accept_enabled,
        "threshold": normalized_threshold,
        "score": score,
        "auto_apply": auto_apply,
        "reasons": reasons,
        "review_reasons": list(dict.fromkeys(review_reasons)),
        "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
    }


def _is_brand_like_category(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return bool(normalized and "brand" in normalized)


def _is_low_risk_brand_normalization(original: str, suggested: str) -> bool:
    source = _compact_text(original).upper()
    target = _compact_text(suggested).upper()
    return bool(source and target and source == target and source != str(original or "").strip())


def _contains_ascii_letters(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", str(text or "")))


def _text_already_contains_suggested_form(*, text: str, suggested: str, original: str) -> bool:
    normalized_text = _compact_text(text).upper()
    normalized_suggested = _compact_text(suggested).upper()
    normalized_original = _compact_text(original).upper()
    if not normalized_text or not normalized_suggested or normalized_original == normalized_suggested:
        return False
    return normalized_suggested in normalized_text


def _profile_mentions_term(profile: dict[str, Any] | None, term: str) -> bool:
    candidate = _compact_text(term).upper()
    if not candidate or not isinstance(profile, dict):
        return False
    for key in ("subject", "content_subject", "subject_brand", "subject_model", "summary", "content_summary"):
        value = _compact_text(profile.get(key) or "").upper()
        if value and candidate in value:
            return True
    return False


def _is_profile_confirmed_brand_alias_rewrite(
    *,
    original: str,
    suggested: str,
    wrong_form: str,
    content_profile: dict[str, Any] | None,
) -> bool:
    source = str(original or "").strip()
    target = str(suggested or "").strip()
    wrong = str(wrong_form or "").strip()
    if not source or not target or not wrong:
        return False
    if source.casefold() != wrong.casefold():
        return False
    if not _profile_mentions_term(content_profile, target):
        return False
    compact_source = _compact_text(source)
    compact_target = _compact_text(target)
    if len(compact_source) < 2 or len(compact_target) < 3:
        return False
    if _is_low_risk_brand_normalization(source, target):
        return True
    return _contains_cjk(source) and _contains_ascii_letters(target)


def _filter_conflicting_model_wrong_forms(correct_form: str, wrong_forms: list[Any]) -> list[str]:
    return _shared_filter_conflicting_model_wrong_forms(correct_form=correct_form, wrong_forms=wrong_forms)


async def apply_glossary_corrections(
    job_id: uuid.UUID,
    subtitle_items: list[SubtitleItem],
    session: AsyncSession,
    *,
    glossary_terms: list[GlossaryTerm | dict[str, Any]] | None = None,
    content_profile: dict[str, Any] | None = None,
) -> list[SubtitleCorrection]:
    """
    Glossary normalization is disabled. RoughCut now uses glossary/user memory
    terms only as transcription hotwords and never creates text-rewrite
    correction candidates from wrong_forms.
    """
    await session.flush()
    return disabled_correction_candidates()


def apply_corrections_to_text(text: str, corrections: list[SubtitleCorrection]) -> str:
    """Glossary text rewrites are disabled; return the original text."""
    return disabled_text_rewrite(text)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def _has_token_boundaries(text: str, start: int, end: int) -> bool:
    left = text[start - 1] if start > 0 else ""
    right = text[end] if end < len(text) else ""
    return (not left or not left.isalnum()) and (not right or not right.isalnum())
