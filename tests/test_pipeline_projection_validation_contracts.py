from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.media import subtitle_projection_validation as projection_validation_module
from roughcut.pipeline import steps as pipeline_steps


def _build_fake_validation(repaired_payload: list[dict[str, object]]) -> SimpleNamespace:
    return SimpleNamespace(
        mismatch_detected=True,
        fallback_used=False,
        subtitles=repaired_payload,
        changed=True,
        input_count=1,
        output_count=len(repaired_payload),
    )


@pytest.mark.asyncio
async def test_resolve_audio_artifact_rebuilds_missing_storage_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mov"
    source_path.write_bytes(b"video")
    stored_root = tmp_path / "stored"
    artifact = SimpleNamespace(storage_path=f"jobs/{job_id}/audio.wav")
    job = SimpleNamespace(id=job_id, source_path=str(source_path), source_name="source.mov")
    step = SimpleNamespace(
        metadata_={},
        step_name="transcribe",
        started_at=None,
        finished_at=None,
    )

    class FakeSession:
        async def commit(self) -> None:
            return None

    class FakeStorage:
        async def async_upload_file(self, local_path: Path, key: str) -> str:
            target = self.resolve_path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local_path, target)
            return key

        def resolve_path(self, key: str) -> Path:
            return stored_root / str(key).removeprefix("jobs/")

    async def fake_resolve_storage_reference(*args, **kwargs):
        raise FileNotFoundError("missing-audio")

    async def fake_resolve_source(_job, _tmpdir: str) -> Path:
        return source_path

    async def fake_extract_audio(_source: Path, output_path: Path) -> Path:
        output_path.write_bytes(b"wav")
        return output_path

    monkeypatch.setattr(pipeline_steps, "_resolve_storage_reference", fake_resolve_storage_reference)
    monkeypatch.setattr(pipeline_steps, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(pipeline_steps, "extract_audio", fake_extract_audio)
    monkeypatch.setattr(pipeline_steps, "get_storage", lambda: FakeStorage())

    rebuilt = await pipeline_steps._resolve_audio_artifact_or_rebuild(
        FakeSession(),
        job=job,
        step=step,
        audio_artifact=artifact,
        tmpdir=str(tmp_path),
    )

    assert rebuilt is not None
    assert rebuilt.read_bytes() == b"wav"
    assert artifact.storage_path == f"jobs/{job_id}/audio.wav"
    assert (stored_root / str(job_id) / "audio.wav").read_bytes() == b"wav"
    assert step.metadata_["audio_artifact_rebuilt"] is True
    assert step.metadata_["has_audio"] is True


def test_subtitle_projection_repair_summary_does_not_treat_annotation_only_changes_as_repair() -> None:
    validation = SimpleNamespace(
        mismatch_detected=False,
        fallback_used=False,
        changed=True,
        input_count=1,
        output_count=1,
    )

    assert pipeline_steps._subtitle_projection_repair_summary(
        validation=validation,
        apply_repair=True,
    ) == {
        "repair_requested": True,
        "repair_applied": False,
        "mismatch_detected": False,
        "fallback_used": False,
        "changed": True,
        "annotation_changed": True,
        "input_count": 1,
        "output_count": 1,
        "repair_mode": None,
    }


@pytest.mark.asyncio
async def test_validated_subtitle_projection_for_timeline_without_repair_keeps_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    source_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    keep_segments = [{"start": 0.0, "end": 1.0}]
    diagnostics: dict[str, object] = {}

    def fake_validate(
        _projected_subtitles: list[dict[str, object]],
        *,
        source_subtitles: list[dict[str, object]],
        keep_segments: list[dict[str, object]],
        fallback_source_subtitles: list[dict[str, object]] | None = None,
        apply_annotation_repair: bool = False,
    ) -> SimpleNamespace:
        assert apply_annotation_repair is False
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
        diagnostics_slot=diagnostics,
    )

    # 在未显式 request repair 时，返回必须是输入投影行，不应被 validate 返回值覆盖。
    assert result == projected_subtitles
    assert result[0]["text_final"] == "原始内容"
    assert diagnostics == {
        "repair_requested": False,
        "repair_applied": False,
        "mismatch_detected": True,
        "fallback_used": False,
        "changed": True,
        "annotation_changed": False,
        "input_count": 1,
        "output_count": 1,
        "repair_mode": None,
    }


@pytest.mark.asyncio
async def test_validated_subtitle_projection_for_timeline_with_repair_uses_validation_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    source_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    keep_segments = [{"start": 0.0, "end": 1.0}]
    repaired = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}]
    diagnostics: dict[str, object] = {}

    def fake_validate(
        _projected_subtitles: list[dict[str, object]],
        *,
        source_subtitles: list[dict[str, object]],
        keep_segments: list[dict[str, object]],
        fallback_source_subtitles: list[dict[str, object]] | None = None,
        apply_annotation_repair: bool = False,
    ) -> SimpleNamespace:
        assert apply_annotation_repair is True
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
        diagnostics_slot=diagnostics,
    )

    assert result == repaired
    assert result[0]["text_final"] == "修复结果"
    assert diagnostics == {
        "repair_requested": True,
        "repair_applied": True,
        "mismatch_detected": True,
        "fallback_used": False,
        "changed": True,
        "annotation_changed": False,
        "input_count": 1,
        "output_count": 1,
        "repair_mode": "projection_annotation_repair",
    }


@pytest.mark.asyncio
async def test_validated_subtitle_projection_for_timeline_repair_permission_controls_fallback_source_passed_to_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    source_subtitles = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    keep_segments = [{"start": 0.0, "end": 1.0}]
    diagnostics: dict[str, object] = {}
    fallback_seen: list[list[dict[str, object]] | None] = [None]

    def fake_validate(
        _projected_subtitles: list[dict[str, object]],
        *,
        source_subtitles: list[dict[str, object]],
        keep_segments: list[dict[str, object]],
        fallback_source_subtitles: list[dict[str, object]] | None = None,
        apply_annotation_repair: bool = False,
    ) -> SimpleNamespace:
        fallback_seen[0] = list(fallback_source_subtitles) if fallback_source_subtitles is not None else None
        assert apply_annotation_repair is True
        return _build_fake_validation(
            [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}],
        )

    monkeypatch.setattr(pipeline_steps, "validate_projected_subtitles_against_source", fake_validate)

    result = await pipeline_steps._validated_subtitle_projection_for_timeline(
        session=None,
        job_id=uuid.uuid4(),
        projected_subtitles=projected_subtitles,
        keep_segments=keep_segments,
        source_subtitles=source_subtitles,
        fallback_source_subtitles=source_subtitles,
        apply_repair=True,
        diagnostics_slot=diagnostics,
    )

    assert result == [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}]
    assert fallback_seen[0] is None

    explicit_diagnostics: dict[str, object] = {}
    await pipeline_steps._validated_subtitle_projection_for_timeline(
        session=None,
        job_id=uuid.uuid4(),
        projected_subtitles=projected_subtitles,
        keep_segments=keep_segments,
        source_subtitles=source_subtitles,
        fallback_source_subtitles=source_subtitles,
        allow_source_fallback_repair=True,
        apply_repair=True,
        diagnostics_slot=explicit_diagnostics,
    )

    assert explicit_diagnostics["repair_requested"] is True
    assert explicit_diagnostics["repair_applied"] is True
    assert fallback_seen[0] == source_subtitles


def test_validate_projected_subtitles_against_source_is_non_mutating_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repaired_calls: list[bool] = []

    monkeypatch.setattr(
        projection_validation_module,
        "annotate_projected_subtitle_sources",
        lambda projected_subtitles, *_args, **_kwargs: list(projected_subtitles),
    )
    monkeypatch.setattr(
        projection_validation_module,
        "projection_has_source_text_mismatch",
        lambda _annotated, _source_subtitles: False,
    )

    def fake_repair(
        projected_subtitles: list[dict[str, object]],
        *,
        source_subtitles: list[dict[str, object]],
        keep_segments: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        repaired_calls.append(True)
        return [{"index": 99, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}]

    monkeypatch.setattr(
        projection_validation_module,
        "_repair_projection_text_drift_from_span_fallback",
        fake_repair,
    )

    original = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    result = projection_validation_module.validate_projected_subtitles_against_source(
        original,
        source_subtitles=original,
        keep_segments=[{"start": 0.0, "end": 1.0}],
        apply_annotation_repair=False,
    )

    assert repaired_calls == []
    assert result.subtitles == original
    assert result.changed is False


def test_validate_projected_subtitles_against_source_only_repairs_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        projection_validation_module,
        "annotate_projected_subtitle_sources",
        lambda projected_subtitles, *_args, **_kwargs: list(projected_subtitles),
    )
    monkeypatch.setattr(
        projection_validation_module,
        "projection_has_source_text_mismatch",
        lambda _annotated, _source_subtitles: False,
    )
    monkeypatch.setattr(
        projection_validation_module,
        "_repair_projection_text_drift_from_span_fallback",
        lambda _projected_subtitles, **_kwargs: [
            {"index": 99, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}
        ],
    )

    original = [{"index": 1, "start_time": 0.0, "end_time": 1.0, "text_final": "原始内容"}]
    result = projection_validation_module.validate_projected_subtitles_against_source(
        original,
        source_subtitles=original,
        keep_segments=[{"start": 0.0, "end": 1.0}],
        apply_annotation_repair=True,
    )

    assert result.subtitles == [{"index": 99, "start_time": 0.0, "end_time": 1.0, "text_final": "修复结果"}]
    assert result.changed is True
