from __future__ import annotations

import shutil
import uuid
from types import SimpleNamespace

import pytest

from roughcut.pipeline import steps


@pytest.mark.asyncio
async def test_render_stage_cache_restores_only_matching_fingerprint(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    async def fake_probe(path):
        assert path.exists()
        return SimpleNamespace(duration=1.0)

    async def fake_copy(source_path, dest_path, **_kwargs):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)

    monkeypatch.setattr(steps, "_probe_with_retry", fake_probe)
    monkeypatch.setattr(steps, "_copy_file_with_retry", fake_copy)

    source = tmp_path / "stage-output.mp4"
    source.write_bytes(b"stage")
    cache_path = tmp_path / "cache" / "plain.mp4"
    restored = tmp_path / "restored.mp4"
    fingerprint = {"schema": "render_stage_fingerprint.v1", "stage": "plain", "input": "a"}

    await steps._store_render_stage_cache(
        stage_name="plain",
        working_path=source,
        cache_path=cache_path,
        fingerprint=fingerprint,
    )

    assert await steps._restore_render_stage_cache(
        stage_name="plain",
        cache_path=cache_path,
        working_path=restored,
        fingerprint=fingerprint,
    )
    assert restored.read_bytes() == b"stage"

    restored.unlink()
    assert not await steps._restore_render_stage_cache(
        stage_name="plain",
        cache_path=cache_path,
        working_path=restored,
        fingerprint={**fingerprint, "input": "b"},
    )
    assert not restored.exists()


def test_render_stage_fingerprint_changes_when_timeline_or_subtitle_inputs_change() -> None:
    job = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        file_hash="source-hash",
        workflow_mode="smart_assist",
        enhancement_modes=["ai_effects"],
    )
    editorial_timeline = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        version=1,
        data_json={"segments": [{"start": 0, "end": 1}]},
    )
    render_plan_timeline = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
        version=1,
        data_json={"packaging_timeline": {"packaging": {}}},
    )

    base = steps._build_render_stage_fingerprint(
        job=job,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
        subtitle_dicts=[{"start_time": 0.0, "end_time": 1.0, "text_final": "A"}],
        projection_data={"schema": "projection.v1"},
        source_subtitles=[],
        extra={"stage": "plain"},
    )
    changed_subtitle = steps._build_render_stage_fingerprint(
        job=job,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
        subtitle_dicts=[{"start_time": 0.0, "end_time": 1.0, "text_final": "B"}],
        projection_data={"schema": "projection.v1"},
        source_subtitles=[],
        extra={"stage": "plain"},
    )
    render_plan_timeline.version = 2
    changed_timeline = steps._build_render_stage_fingerprint(
        job=job,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
        subtitle_dicts=[{"start_time": 0.0, "end_time": 1.0, "text_final": "A"}],
        projection_data={"schema": "projection.v1"},
        source_subtitles=[],
        extra={"stage": "plain"},
    )

    assert changed_subtitle != base
    assert changed_timeline != base


def test_render_stage_fingerprint_includes_render_contract_version(monkeypatch: pytest.MonkeyPatch) -> None:
    job = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        file_hash="source-hash",
        workflow_mode="smart_assist",
        enhancement_modes=["ai_effects"],
    )
    editorial_timeline = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        version=1,
        data_json={"segments": [{"start": 0, "end": 1}]},
    )
    render_plan_timeline = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
        version=1,
        data_json={"packaging_timeline": {"packaging": {}}},
    )

    base = steps._build_render_stage_fingerprint(
        job=job,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
        subtitle_dicts=[],
        projection_data={},
        source_subtitles=[],
        extra={"stage": "packaged_candidate"},
    )
    monkeypatch.setattr(steps, "_RENDER_STAGE_CONTRACT_VERSION", "render_stage_contract.test.bump")
    bumped = steps._build_render_stage_fingerprint(
        job=job,
        editorial_timeline=editorial_timeline,
        render_plan_timeline=render_plan_timeline,
        subtitle_dicts=[],
        projection_data={},
        source_subtitles=[],
        extra={"stage": "packaged_candidate"},
    )

    assert base["render_contract_version"] == "render_stage_contract.v8.enhanced_body_only_bookends"
    assert bumped["render_contract_version"] == "render_stage_contract.test.bump"
    assert bumped != base


def test_resolve_requested_render_variants_defaults_to_standard_output() -> None:
    job = SimpleNamespace(enhancement_modes=[])

    assert steps.resolve_requested_render_variants(job, {}) == ["packaged"]


def test_resolve_requested_render_variants_keeps_enhancements_as_unified_output_contract() -> None:
    job = SimpleNamespace(enhancement_modes=["ai_effects"])

    assert steps.resolve_requested_render_variants(job, {}) == ["packaged"]


def test_render_variant_delivery_file_contract_hides_internal_variants() -> None:
    requested = ["packaged", "plain", "ai_effect", "avatar"]

    assert steps._render_variant_writes_delivery_file("packaged", requested)
    assert steps._render_variant_writes_delivery_file("enhanced", requested)
    assert not steps._render_variant_writes_delivery_file("plain", requested)
    assert not steps._render_variant_writes_delivery_file("ai_effect", requested)
    assert not steps._render_variant_writes_delivery_file("avatar", requested)


def test_bookendless_packaging_context_only_removes_intro_outro() -> None:
    context = {
        "packaging_timeline": {
            "packaging": {
                "intro": {"path": "intro.mp4"},
                "outro": {"path": "outro.mp4"},
                "insert": {"path": "insert.mp4"},
                "watermark": {"path": "watermark.png"},
            }
        },
        "assets": {
            "intro": {"path": "intro.mp4"},
            "outro": {"path": "outro.mp4"},
            "insert": {"path": "insert.mp4"},
            "watermark": {"path": "watermark.png"},
            "music": {"path": "music.mp3"},
        },
        "has_packaging": True,
        "has_packaging_assets": True,
    }

    result = steps._bookendless_packaging_context(context)

    assert result["assets"]["intro"] is None
    assert result["assets"]["outro"] is None
    assert result["assets"]["insert"] == {"path": "insert.mp4"}
    assert result["assets"]["watermark"] == {"path": "watermark.png"}
    assert result["assets"]["music"] == {"path": "music.mp3"}
    assert result["packaging_timeline"]["packaging"]["intro"] is None
    assert result["packaging_timeline"]["packaging"]["outro"] is None
    assert result["packaging_timeline"]["packaging"]["insert"] == {"path": "insert.mp4"}
    assert result["has_packaging"] is True


def test_shift_subtitle_items_by_offset_keeps_body_timing_contract() -> None:
    shifted = steps._shift_subtitle_items_by_offset(
        [{"start_time": 1.0, "end_time": 2.5, "text": "body"}],
        offset_sec=3.0,
    )

    assert shifted == [{"start_time": 4.0, "end_time": 5.5, "text": "body"}]


def test_map_avatar_segments_to_variant_timeline_applies_final_packaging_offsets() -> None:
    mapped = steps._map_avatar_segments_to_variant_timeline(
        [{"segment_id": "a", "start_time": 5.0, "end_time": 7.0}],
        timeline_mapping={
            "transition_offsets": [(4.0, 0.5)],
            "intro_duration_sec": 1.0,
        },
    )

    assert mapped == [{"segment_id": "a", "start_time": 5.5, "end_time": 7.5}]


@pytest.mark.asyncio
async def test_render_phase_outputs_validation_requires_requested_variant(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    async def fake_probe(path):
        assert path.exists()
        return SimpleNamespace(duration=1.0, width=1920, height=1080)

    monkeypatch.setattr(steps, "_probe_with_retry", fake_probe)
    plain = tmp_path / "plain.mp4"
    packaged = tmp_path / "packaged.mp4"
    plain.write_bytes(b"plain")
    packaged.write_bytes(b"packaged")

    with pytest.raises(RuntimeError, match="requested variant missing ai_effect"):
        await steps._validate_render_phase_outputs_for_finalize(
            {
                "schema": steps.ARTIFACT_TYPE_RENDER_PHASE_OUTPUTS,
                "phase": "burn_in",
                "requested_variants": ["packaged", "ai_effect"],
                "variants": {
                    "plain": {"cache_path": str(plain), "subtitles": []},
                    "packaged": {"cache_path": str(packaged), "subtitles": []},
                },
            }
        )


def test_delete_render_stage_cache_removes_video_and_metadata(tmp_path) -> None:
    cache_path = tmp_path / "packaged_candidate.mp4"
    metadata_path = steps._render_stage_cache_metadata_path(cache_path)
    cache_path.write_bytes(b"bad-cache")
    metadata_path.write_text("{}", encoding="utf-8")

    steps._delete_render_stage_cache(cache_path)

    assert not cache_path.exists()
    assert not metadata_path.exists()
