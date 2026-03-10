from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from fastcut.db.models import Timeline
from fastcut.edit.decisions import EditDecision


async def save_editorial_timeline(
    job_id: uuid.UUID,
    decision: EditDecision,
    session: AsyncSession,
    version: int = 1,
) -> Timeline:
    """Persist editorial timeline to database."""
    timeline = Timeline(
        job_id=job_id,
        version=version,
        timeline_type="editorial",
        data_json=decision.to_dict(),
    )
    session.add(timeline)
    await session.flush()
    return timeline
