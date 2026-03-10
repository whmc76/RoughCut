from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastcut.db.models import Job, SubtitleCorrection, SubtitleItem


@dataclass
class CorrectionReport:
    job_id: str
    generated_at: str
    total_subtitle_items: int
    total_corrections: int
    corrections_by_type: dict[str, int]
    pending_count: int
    accepted_count: int
    rejected_count: int
    items: list[dict] = field(default_factory=list)


async def generate_report(job_id: uuid.UUID, session: AsyncSession) -> CorrectionReport:
    """Generate a subtitle correction review report for a job."""
    # Load subtitle items with corrections
    items_result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id)
        .order_by(SubtitleItem.item_index)
    )
    subtitle_items = items_result.scalars().all()

    corrections_result = await session.execute(
        select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id)
    )
    corrections = corrections_result.scalars().all()

    # Build correction index
    corrections_by_item: dict[uuid.UUID, list[SubtitleCorrection]] = {}
    for corr in corrections:
        if corr.subtitle_item_id:
            corrections_by_item.setdefault(corr.subtitle_item_id, []).append(corr)

    corrections_by_type: dict[str, int] = {}
    pending = accepted = rejected = 0

    for corr in corrections:
        corrections_by_type[corr.change_type] = corrections_by_type.get(corr.change_type, 0) + 1
        if corr.human_decision == "accepted":
            accepted += 1
        elif corr.human_decision == "rejected":
            rejected += 1
        else:
            pending += 1

    report_items: list[dict] = []
    for item in subtitle_items:
        item_corrections = corrections_by_item.get(item.id, [])
        report_items.append(
            {
                "index": item.item_index,
                "start": item.start_time,
                "end": item.end_time,
                "text_raw": item.text_raw,
                "text_norm": item.text_norm,
                "text_final": item.text_final,
                "corrections": [
                    {
                        "id": str(c.id),
                        "original": c.original_span,
                        "suggested": c.suggested_span,
                        "type": c.change_type,
                        "confidence": c.confidence,
                        "source": c.source,
                        "decision": c.human_decision,
                        "override": c.human_override,
                    }
                    for c in item_corrections
                ],
            }
        )

    return CorrectionReport(
        job_id=str(job_id),
        generated_at=datetime.utcnow().isoformat(),
        total_subtitle_items=len(subtitle_items),
        total_corrections=len(corrections),
        corrections_by_type=corrections_by_type,
        pending_count=pending,
        accepted_count=accepted,
        rejected_count=rejected,
        items=report_items,
    )
