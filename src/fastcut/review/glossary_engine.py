from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastcut.db.models import GlossaryTerm, SubtitleCorrection, SubtitleItem


@dataclass
class CorrectionSuggestion:
    subtitle_item_id: uuid.UUID
    original_span: str
    suggested_span: str
    change_type: str
    confidence: float
    source: str


async def apply_glossary_corrections(
    job_id: uuid.UUID,
    subtitle_items: list[SubtitleItem],
    session: AsyncSession,
) -> list[SubtitleCorrection]:
    """
    Match all glossary terms against subtitle text.
    Returns created SubtitleCorrection rows.
    """
    # Load all glossary terms
    result = await session.execute(select(GlossaryTerm))
    terms = result.scalars().all()

    corrections: list[SubtitleCorrection] = []

    for item in subtitle_items:
        text = item.text_norm or item.text_raw

        for term in terms:
            for wrong_form in term.wrong_forms:
                # Case-insensitive match
                pattern = re.compile(re.escape(wrong_form), re.IGNORECASE | re.UNICODE)
                for match in pattern.finditer(text):
                    original = match.group(0)
                    if original == term.correct_form:
                        continue  # Already correct

                    correction = SubtitleCorrection(
                        job_id=job_id,
                        subtitle_item_id=item.id,
                        original_span=original,
                        suggested_span=term.correct_form,
                        change_type="glossary",
                        confidence=0.95,
                        source="glossary_match",
                        auto_applied=False,
                        human_decision="pending",
                    )
                    session.add(correction)
                    corrections.append(correction)

    await session.flush()
    return corrections


def apply_corrections_to_text(text: str, corrections: list[SubtitleCorrection]) -> str:
    """Apply all auto-approved corrections to the text string."""
    result = text
    for correction in corrections:
        if correction.auto_applied or correction.human_decision == "accepted":
            override = correction.human_override or correction.suggested_span
            result = result.replace(correction.original_span, override, 1)
    return result
