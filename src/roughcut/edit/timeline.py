from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import Timeline
from roughcut.edit.decisions import EditDecision


async def save_editorial_timeline(
    job_id: uuid.UUID,
    decision: EditDecision,
    session: AsyncSession,
    version: int | None = None,
) -> Timeline:
    """Persist editorial timeline to database."""
    if version is None:
        result = await session.execute(
            select(func.max(Timeline.version)).where(
                Timeline.job_id == job_id,
                Timeline.timeline_type == "editorial",
            )
        )
        version = int(result.scalar() or 0) + 1
    timeline = Timeline(
        job_id=job_id,
        version=version,
        timeline_type="editorial",
        data_json=decision.to_dict(),
    )
    session.add(timeline)
    await session.flush()
    return timeline
