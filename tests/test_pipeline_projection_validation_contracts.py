from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from roughcut.pipeline import steps as pipeline_steps


def _build_fake_validation(repaired_payload: list[dict[str, object]]) -> SimpleNamespace:
    return SimpleNamespace(
        mismatch_detected=True,
        fallback_used=False,
        subtitles=repaired_payload,
    )


@pytest.mark.asyncio
async def test_validated_subtitle_projection_for_timeline_without_repair_keeps_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    source_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    keep_segments = [{"start": 0.0, "end": 1.0}]

    def fake_validate(
        _projected_subtitles: list[dict[str, object]],
        *,
        source_subtitles: list[dict[str, object]],
        keep_segments: list[dict[str, object]],
        fallback_source_subtitles: list[dict[str, object]] | None = None,
    ) -> SimpleNamespace:
        return _build_fake_validation(
            [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}],
        )

    monkeypatch.setattr(
        pipeline_steps,
        "validate_projected_subtitles_against_source",
        fake_validate,
    )

    result = await pipeline_steps._validated_subtitle_projection_for_timeline(
        session=None,
        job_id=uuid.uuid4(),
        projected_subtitles=projected_subtitles,
        keep_segments=keep_segments,
        source_subtitles=source_subtitles,
        fallback_source_subtitles=source_subtitles,
        apply_repair=False,
    )

    # 在未显式 request repair 时，返回必须是输入投影行，不应被 validate 返回值覆盖。
    assert result == projected_subtitles
    assert result[0]["text_final"] == "原始内容"


@pytest.mark.asyncio
async def test_validated_subtitle_projection_for_timeline_with_repair_uses_validation_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    source_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    keep_segments = [{"start": 0.0, "end": 1.0}]
    repaired = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}]

    def fake_validate(
        _projected_subtitles: list[dict[str, object]],
        *,
        source_subtitles: list[dict[str, object]],
        keep_segments: list[dict[str, object]],
        fallback_source_subtitles: list[dict[str, object]] | None = None,
    ) -> SimpleNamespace:
        return _build_fake_validation(repaired)

    monkeypatch.setattr(pipeline_steps, "validate_projected_subtitles_against_source", fake_validate)

    result = await pipeline_steps._validated_subtitle_projection_for_timeline(
        session=None,
        job_id=uuid.uuid4(),
        projected_subtitles=projected_subtitles,
        keep_segments=keep_segments,
        source_subtitles=source_subtitles,
        fallback_source_subtitles=source_subtitles,
        apply_repair=True,
    )

    assert result == repaired
    assert result[0]["text_final"] == "修复结果"
