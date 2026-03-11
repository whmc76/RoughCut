from __future__ import annotations

import uuid

import pytest

from roughcut.edit.render_plan import build_render_plan


def test_build_render_plan_defaults():
    timeline_id = uuid.uuid4()
    plan = build_render_plan(editorial_timeline_id=timeline_id)

    assert plan["editorial_timeline_id"] == str(timeline_id)
    assert plan["workflow_preset"] == "unboxing_default"
    assert plan["loudness"]["target_lufs"] == -14.0
    assert plan["loudness"]["peak_limit"] == -1.0
    assert plan["voice_processing"]["noise_reduction"] is True
    assert plan["subtitles"]["style"] == "bold_yellow_outline"
    assert plan["cover"]["variant_count"] == 5
    assert plan["intro"] is None
    assert plan["outro"] is None
    assert plan["insert"] is None
    assert plan["watermark"] is None
    assert plan["music"] is None


def test_build_render_plan_custom():
    timeline_id = uuid.uuid4()
    plan = build_render_plan(
        editorial_timeline_id=timeline_id,
        workflow_preset="unboxing_upgrade",
        target_lufs=-16.0,
        noise_reduction=False,
        subtitle_style="white_minimal",
    )
    assert plan["workflow_preset"] == "unboxing_upgrade"
    assert plan["loudness"]["target_lufs"] == -16.0
    assert plan["voice_processing"]["noise_reduction"] is False
    assert plan["subtitles"]["style"] == "white_minimal"
    assert plan["cover"]["style"] == "upgrade_spotlight"
