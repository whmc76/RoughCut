from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from fastcut.db.models import Timeline


def build_render_plan(
    editorial_timeline_id: uuid.UUID,
    *,
    subtitle_version: int = 1,
    subtitle_style: str = "bold_yellow_outline",
    target_lufs: float = -14.0,
    peak_limit: float = -1.0,
    noise_reduction: bool = True,
    intro: dict | None = None,
    outro: dict | None = None,
    watermark: dict | None = None,
    music: dict | None = None,
) -> dict:
    return {
        "editorial_timeline_id": str(editorial_timeline_id),
        "loudness": {
            "target_lufs": target_lufs,
            "peak_limit": peak_limit,
        },
        "voice_processing": {
            "noise_reduction": noise_reduction,
            "compression": "gentle",
        },
        "subtitles": {
            "style": subtitle_style,
            "version": subtitle_version,
        },
        "intro": intro,
        "outro": outro,
        "watermark": watermark,
        "music": music,
    }


async def save_render_plan(
    job_id: uuid.UUID,
    render_plan: dict,
    session: AsyncSession,
    version: int = 1,
) -> Timeline:
    timeline = Timeline(
        job_id=job_id,
        version=version,
        timeline_type="render_plan",
        data_json=render_plan,
    )
    session.add(timeline)
    await session.flush()
    return timeline
