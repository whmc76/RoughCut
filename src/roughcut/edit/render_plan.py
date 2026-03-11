from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.edit.presets import get_workflow_preset
from roughcut.db.models import Timeline


def build_render_plan(
    editorial_timeline_id: uuid.UUID,
    *,
    workflow_preset: str = "unboxing_default",
    subtitle_version: int = 1,
    subtitle_style: str = "bold_yellow_outline",
    target_lufs: float = -14.0,
    peak_limit: float = -1.0,
    noise_reduction: bool = True,
    intro: dict | None = None,
    outro: dict | None = None,
    insert: dict | None = None,
    watermark: dict | None = None,
    music: dict | None = None,
) -> dict:
    preset = get_workflow_preset(workflow_preset)
    return {
        "editorial_timeline_id": str(editorial_timeline_id),
        "workflow_preset": preset.name,
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
        "insert": insert,
        "watermark": watermark,
        "music": music,
        "cover": {
            "style": preset.cover_style,
            "variant_count": preset.cover_variant_count,
        },
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
