import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException

from roughcut.api import jobs as jobs_module
from roughcut.pipeline import steps as pipeline_steps_module
from roughcut.api.jobs import ManualEditorApplyIn
from roughcut.edit import render_plan as render_plan_module
from roughcut.api.jobs import (
    _apply_manual_subtitle_overrides,
    _annotate_manual_projected_subtitle_sources,
    _build_activity_decisions,
    _manual_editor_align_source_rows_to_asr_words,
    _attach_manual_editor_words_to_subtitles,
    _build_editorial_segments_from_keep_segments,
    _build_otio_style_manual_tracks,
    _clean_manual_editor_subtitle_projection,
    _download_file_cache_get,
    _download_file_cache_set,
    _invalidate_job_file_response_cache,
    _inline_file_response,
    _manual_editor_has_collapsed_repeat_runs,
    _manual_editor_draft_subtitles_are_stale,
    _manual_editor_draft_subtitles_match_fingerprint,
    _manual_editor_request_subtitles_match_fingerprint,
    _manual_editor_rerun_issue_code,
    _validate_manual_editor_subtitle_revision,
    _manual_editor_silence_payload,
    _manual_editor_subtitle_fingerprint,
    _manual_editor_subtitle_payload,
    _manual_editor_should_use_clean_fallback_projection,
    _manual_editor_stored_projection_matches_subtitles,
    _manual_editor_timeline_matches_current_subtitles,
    _manual_editor_timeline_subtitle_fingerprint,
    _manual_editor_word_payload,
    _manual_editor_projection_data_uses_canonical,
    _manual_editor_projection_data_is_current,
    _manual_editor_projection_entries_use_canonical,
    _manual_editor_canonical_layer_namespace,
    _manual_editor_apply_conflict_detail,
    _manual_editor_sanitize_projection_item,
    _manual_editor_transcript_projection_blocking_is_significant,
    _manual_editor_apply_source_text_corrections,
    _manual_editor_apply_transcript_hotword_corrections,
    _manual_editor_asset_path,
    _manual_editor_apply_detail,
    _manual_editor_canonical_segment_source_rows,
    _manual_editor_change_contract,
    _manual_editor_change_plan,
    _manual_editor_rerun_plan,
    _manual_editor_choose_source_subtitle_rows,
    _manual_editor_cut_analysis_payload,
    _manual_editor_prerequisite_detail,
    _manual_editor_preview_assets_response,
    _manual_editor_base_keep_segment_dicts,
    _manual_editor_build_refine_decision_plan_from_render_plan,
    _manual_editor_editorial_context,
    _manual_editor_projection_rows_as_source_rows,
    _load_manual_editor_cut_analysis_payload,
    _load_manual_editor_source_subtitle_dicts,
    _load_manual_editor_multimodal_trim_review_payload,
    _manual_editor_apply_frontend_managed_auto_cuts,
    _manual_editor_restore_frontend_managed_auto_cuts,
    _manual_editor_smart_cut_rules_payload,
    _manual_editor_source_fallback_projection_items,
    _manual_editor_normalize_word_payloads_for_text,
    _manual_editor_packaging_plan_from_render_plan,
    _manual_editor_render_plan_context,
    _manual_video_transform_from_render_plan,
    _manual_editor_projected_subtitles_have_duplicate_source_overlap,
    _manual_editor_projection_baseline_rows,
    _manual_editor_authoritative_projection_items,
    _manual_editor_projection_should_use_source_fallback,
    _manual_editor_projection_contract_locked,
    _manual_editor_should_apply_source_projection_fallback,
    _manual_editor_profile_has_vertical_glossary_evidence,
    _manual_editor_reveal_source_asr_words,
    _manual_editor_rule_segments,
    _manual_editor_source_row_split_diagnostics,
    _manual_editor_split_pieces_cover_source_text,
    _manual_editor_subtitle_item_source_rows,
    _manual_editor_split_long_subtitle_rows,
    _manual_projection_has_source_text_mismatch,
    _manual_keep_segments_from_editorial_payload,
    _manual_editor_transcript_source_rows,
    _source_file_cache_get,
    _source_file_cache_set,
    _validate_manual_editor_base_revision,
    _manual_keep_segments_changed,
    _normalize_manual_keep_segments,
)
from roughcut.edit.manual_editor_contract import manual_editor_change_contract_is_consistent
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.cut_analysis import (
    build_cut_analysis_payload,
    cut_analysis_candidate_items,
    cut_analysis_effective_applied_cuts,
)
from roughcut.edit.editorial_timeline import (
    build_editorial_segments_from_keep_segments as build_shared_editorial_segments_from_keep_segments,
    editorial_cut_segments,
    editorial_timeline_analysis,
    editorial_timeline_segments,
    editorial_timeline_subtitle_projection,
    resolve_editorial_keep_segments,
)
from roughcut.edit.render_plan import (
    render_plan_automatic_gate,
    render_plan_avatar_commentary,
    render_plan_delivery,
    render_plan_dialogue_polish,
    render_plan_loudness,
    render_plan_manual_editor,
    render_plan_video_transform,
    render_plan_voice_processing,
    render_plan_workflow_preset,
)
from roughcut.edit.packaging_timeline import (
    packaging_timeline_asset_plan,
    packaging_timeline_assets,
    packaging_timeline_chapter_cards,
    packaging_timeline_focus_events,
    packaging_timeline_has_editing_accents,
    packaging_timeline_has_packaging_assets,
    packaging_timeline_transitions,
)
from roughcut.edit.strategy_decisions import STRATEGY_CANDIDATE_DECISION_SCHEMA_VERSION
from roughcut.edit.strategy_profile import (
    DEFAULT_STRATEGY_TYPE,
    STRATEGY_PROFILE_SCHEMA_VERSION,
    build_strategy_profile_payload,
    payload_strategy_profile,
    payload_strategy_type,
)
from roughcut.edit.subtitle_surfaces import subtitle_semantic_preview_text, subtitle_spoken_rule_text
from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
    CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
    SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
    SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
    build_subtitle_projection_layer,
    canonical_transcript_data_is_current,
)
from roughcut.edit.refine_decisions import (
    build_refine_decision_plan_from_render_plan,
    build_refine_decision_plan_payload,
    refine_plan_audio_defaults,
    resolve_refine_keep_segments_for_timeline,
)
from roughcut.edit.multimodal_trim_review import (
    apply_multimodal_trim_review_to_cut_analysis,
    build_multimodal_trim_review_payload,
    multimodal_trim_review_auto_cut_candidates,
    _extract_candidate_frame_times,
    _resolve_multimodal_trim_review_timeout_seconds,
    review_multimodal_trim_review_payload,
)
from roughcut.edit.smart_cut_rules import (
    DEFAULT_SMART_CUT_CATCHPHRASES,
    DEFAULT_SMART_CUT_FILLERS,
    normalize_smart_cut_rules_payload,
)
from roughcut.media.render import _resolve_render_keep_segments
from roughcut.media import manual_editor_assets as manual_editor_assets_module
from roughcut.media import output as output_module
from roughcut.media.manual_editor_assets import _fallback_asset_status, _generate_proxy_video, _generate_proxy_webm, _peak_from_pcm, _recommended_preview_gain, _silence_intervals_from_peaks, _thumbnail_timestamps, load_manual_editor_preview_assets, manual_editor_asset_dir
from roughcut.media.subtitle_projection_validation import (
    validate_projected_subtitles_against_source,
    validate_projected_subtitles_against_transcript,
)
from roughcut.pipeline.orchestrator import _artifact_types_for_quality_rerun
from roughcut.pipeline.steps import (
    _build_local_hybrid_projection_entries,
    _canonical_transcript_layer_namespace,
    _build_projection_entries_from_subtitle_items,
    _build_projection_items_from_entries,
    _build_projection_candidate_pool,
    _build_projection_correction_assessment,
    _build_edit_review_bundle_payload,
    _build_fixture_seeded_render_subtitle_asr_alignment,
    _build_strategy_cut_boundary_sample_manifest,
    _build_edited_subtitle_projection,
    _build_variant_timeline_bundle,
    _load_latest_subtitle_payloads,
    _load_source_subtitle_payloads_for_projection_validation,
    _map_editing_accents_to_packaged_timeline,
    _resolve_editorial_analysis_payload,
    _runtime_packaging_context,
    _runtime_render_plan_context,
    _strategy_requires_highlight_boundary_frames,
    _content_profile_is_generated_strategy_replay_fixture,
    _variant_timeline_editorial_context,
    _resolve_packaged_timeline_mapping_context,
    _resolve_transition_overlap_offsets,
    _map_subtitles_to_packaged_timeline,
    _project_canonical_transcript_to_timeline,
    _resolve_packaged_render_variant,
    _subtitle_section_profile_for_time,
    _validate_variant_timeline_bundle,
    _manual_editor_subtitle_items_from_editorial,
    _merge_render_runtime_result,
    _normalize_subtitle_event,
    _persist_render_runtime_diagnostics,
    _persist_projection_layer_to_subtitle_items,
    _projection_boundary_splits_material_token,
    _projection_compact_text,
    _merge_material_split_projection_entries,
    _merge_short_display_boundary_entries,
    _select_projection_candidate,
    _projection_has_suspicious_subtitle_timing,
    _projection_selection_policy,
    _resolve_packaging_trailing_gap_allowance,
    _resolve_keep_segments_from_refine_plan,
    _resolve_projection_split_profile,
    _estimate_render_subtitle_global_offset,
    _drop_clustered_unmatched_render_subtitles,
    _drop_tail_compressed_duplicate_render_subtitles,
    _render_subtitle_alignment_local_cluster_metrics,
    _render_subtitle_alignment_gate_passes,
    _retime_render_subtitle_items_from_alignment_audit,
    _resegment_packaged_subtitles,
    _rewrite_packaged_subtitle_copy,
    _shift_render_subtitle_items,
    _bound_render_subtitles_to_duration,
    _stabilize_render_subtitle_timeline,
    _subtitle_item_payload,
    _subtitle_projection_entry_payload,
    _should_keep_existing_subtitle_projection,
)


def test_merge_render_runtime_result_preserves_stronger_existing_degraded_reason() -> None:
    merged = _merge_render_runtime_result(
        {
            "status": "degraded",
            "reason": "avatar_full_track_call_timeout",
            "detail": "数字人渲染未完成，已自动回退普通成片：avatar_full_track_call_timeout>180.0s",
            "retryable": True,
            "error_metadata": {"call_timeout_seconds": 180.0},
        },
        {
            "status": "degraded",
            "reason": "missing_avatar_render",
            "detail": "没有拿到可用数字人视频，已自动回退普通成片。",
        },
    )

    assert merged == {
        "status": "degraded",
        "reason": "avatar_full_track_call_timeout",
        "detail": "数字人渲染未完成，已自动回退普通成片：avatar_full_track_call_timeout>180.0s",
        "retryable": True,
        "error_metadata": {"call_timeout_seconds": 180.0},
    }


def test_strategy_requires_highlight_boundary_frames_reads_render_policy() -> None:
    assert _strategy_requires_highlight_boundary_frames(
        {
            "strategy_review_gates": {
                "pipeline_plan": {
                    "strategy_policy": {
                        "render_validation_policy": {
                            "check_highlight_boundary_frames": True,
                        }
                    }
                }
            }
        }
    ) is True
    assert _strategy_requires_highlight_boundary_frames(
        {
            "strategy_review_gates": {
                "pipeline_plan": {
                    "strategy_policy": {
                        "render_validation_policy": {
                            "check_cut_boundaries": True,
                        }
                    }
                }
            }
        }
    ) is False


def test_generated_strategy_replay_fixture_detection_is_source_context_scoped() -> None:
    assert _content_profile_is_generated_strategy_replay_fixture(
        {
            "source_context": {
                "fixture_source": "generated_strategy_replay_fixture",
            }
        }
    ) is True
    assert _content_profile_is_generated_strategy_replay_fixture(
        {
            "resolved_profile": {
                "source_context": {
                    "fixture_source": "generated_strategy_replay_fixture",
                }
            }
        }
    ) is True
    assert _content_profile_is_generated_strategy_replay_fixture(
        {
            "source_context": {
                "fixture_source": "user_upload",
            }
        }
    ) is False
    assert _content_profile_is_generated_strategy_replay_fixture({}) is False


def test_fixture_seeded_render_subtitle_alignment_writes_gate_pass_payload(tmp_path: Path) -> None:
    debug_dir = tmp_path / "alignment"
    payload = _build_fixture_seeded_render_subtitle_asr_alignment(
        video_path=tmp_path / "render.mp4",
        subtitle_items=[
                {
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "text_final": "fixture subtitle",
                }
        ],
        debug_dir=debug_dir,
        label="packaged_final",
    )

    assert payload["gate_pass"] is True
    assert payload["fixture_seeded"] is True
    assert payload["provider"] == "fixture_seed"
    assert payload["subtitle_event_count"] == 1
    assert (debug_dir / "packaged_final.subtitle_alignment.json").exists()


@pytest.mark.asyncio
async def test_build_strategy_cut_boundary_sample_manifest_extracts_boundary_frames(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted: list[float] = []

    async def fake_extract_frame(video_path: Path, output_path: Path, *, seek_sec: float) -> None:
        assert video_path == tmp_path / "render.mp4"
        extracted.append(seek_sec)
        output_path.write_bytes(b"frame")

    async def fake_extract_waveform(
        video_path: Path,
        output_path: Path,
        *,
        start_sec: float,
        end_sec: float,
    ) -> None:
        assert video_path == tmp_path / "render.mp4"
        assert start_sec == 0.75
        assert end_sec == 2.25
        output_path.write_text('{"schema":"strategy_cut_boundary_waveform.v1"}', encoding="utf-8")

    monkeypatch.setattr(
        "roughcut.pipeline.steps._extract_strategy_boundary_frame",
        fake_extract_frame,
    )
    monkeypatch.setattr(
        "roughcut.pipeline.steps._extract_strategy_boundary_waveform",
        fake_extract_waveform,
    )
    video_path = tmp_path / "render.mp4"
    video_path.write_bytes(b"video")

    manifest = await _build_strategy_cut_boundary_sample_manifest(
        video_path=video_path,
        debug_dir=tmp_path / "debug",
        cut_boundary_evidence={
            "high_risk_cuts": [
                {
                    "rule_id": "highlight_cut",
                    "start": 1.0,
                    "end": 2.0,
                    "reason": "visual_action",
                    "risk_level": "high",
                    "boundary_keep_energy": 1.25,
                }
            ]
        },
    )

    assert manifest["schema"] == "strategy_cut_boundary_samples.v1"
    assert manifest["sample_count"] == 1
    assert manifest["frame_count"] == 2
    assert manifest["boundary_samples"][0]["cut_id"] == "highlight_cut"
    assert manifest["boundary_samples"][0]["frame_paths"]
    assert manifest["boundary_samples"][0]["waveform_path"].endswith("cut_01_waveform.json")
    assert extracted == [0.88, 2.12]
    assert Path(manifest["manifest_path"]).exists()


@pytest.mark.asyncio
async def test_build_strategy_cut_boundary_sample_manifest_falls_back_to_rule_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted: list[float] = []

    async def fake_extract_frame(video_path: Path, output_path: Path, *, seek_sec: float) -> None:
        extracted.append(seek_sec)
        output_path.write_bytes(b"frame")

    async def fake_extract_waveform(
        video_path: Path,
        output_path: Path,
        *,
        start_sec: float,
        end_sec: float,
    ) -> None:
        output_path.write_text('{"schema":"strategy_cut_boundary_waveform.v1"}', encoding="utf-8")

    monkeypatch.setattr("roughcut.pipeline.steps._extract_strategy_boundary_frame", fake_extract_frame)
    monkeypatch.setattr("roughcut.pipeline.steps._extract_strategy_boundary_waveform", fake_extract_waveform)
    video_path = tmp_path / "render.mp4"
    video_path.write_bytes(b"video")

    manifest = await _build_strategy_cut_boundary_sample_manifest(
        video_path=video_path,
        debug_dir=tmp_path / "debug",
        cut_boundary_evidence={"high_risk_cuts": []},
        cut_analysis={
            "schema": "cut_analysis.v1",
            "accepted_cuts": [],
            "rule_candidates": [
                {
                    "rule_id": "timing_trim:2.823:3.000",
                    "start": 2.823,
                    "end": 3.0,
                    "reason": "timing_trim",
                    "risk_level": "medium",
                }
            ],
        },
    )

    assert manifest["sample_count"] == 1
    assert manifest["boundary_samples"][0]["cut_id"] == "timing_trim:2.823:3.000"
    assert manifest["boundary_samples"][0]["frame_paths"]
    assert extracted == [2.703, 3.12]


@pytest.mark.asyncio
async def test_packaged_timeline_mapping_reuses_intro_and_insert_probe_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_calls: list[str] = []

    async def _fake_probe_media_duration(path: Path) -> float:
        probe_calls.append(path.name)
        if path.name == "intro.mp4":
            return 1.2
        if path.name == "insert.mp4":
            return 0.8
        raise AssertionError(f"unexpected probe path: {path}")

    monkeypatch.setattr("roughcut.pipeline.steps._probe_media_duration", _fake_probe_media_duration)

    render_plan = {
        "packaging_timeline": {
            "editing_accents": {"transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12}},
            "packaging": {
                "intro": {"path": "intro.mp4"},
                "insert": {"path": "insert.mp4", "insert_after_sec": 2.0},
            },
        }
    }
    keep_segments = [{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}]
    timeline_mapping = await _resolve_packaged_timeline_mapping_context(
        render_plan,
        keep_segments=keep_segments,
    )

    subtitles = await _map_subtitles_to_packaged_timeline(
        [{"start_time": 0.0, "end_time": 1.0, "text_final": "demo"}],
        render_plan,
        keep_segments=keep_segments,
        timeline_mapping=timeline_mapping,
    )
    accents = await _map_editing_accents_to_packaged_timeline(
        {"emphasis_overlays": [{"start_time": 0.5, "end_time": 1.0, "text": "demo"}], "sound_effects": []},
        render_plan,
        keep_segments=keep_segments,
        timeline_mapping=timeline_mapping,
    )

    assert subtitles
    assert accents["emphasis_overlays"]
    assert probe_calls == ["intro.mp4", "insert.mp4"]
    assert timeline_mapping["section_profile_context"] == {
        "subtitles": {},
        "timeline_analysis": {},
    }


@pytest.mark.asyncio
async def test_packaged_timeline_mapping_accepts_normalized_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_calls: list[str] = []

    async def _fake_probe_media_duration(path: Path) -> float:
        probe_calls.append(path.name)
        if path.name == "intro.mp4":
            return 1.2
        if path.name == "insert.mp4":
            return 0.8
        raise AssertionError(f"unexpected probe path: {path}")

    monkeypatch.setattr("roughcut.pipeline.steps._probe_media_duration", _fake_probe_media_duration)

    render_plan = {
        "editing_accents": {"transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12}},
        "packaging": {
            "intro": {"path": "intro.mp4"},
            "insert": {"path": "insert.mp4", "insert_after_sec": 2.0},
        },
    }
    keep_segments = [{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}]

    timeline_mapping = await _resolve_packaged_timeline_mapping_context(
        render_plan,
        keep_segments=keep_segments,
    )

    assert timeline_mapping["intro_duration_sec"] == 1.2
    assert timeline_mapping["effective_insert_duration_sec"] == 0.8
    assert timeline_mapping["insert_after_sec"] == 3.2
    assert probe_calls == ["intro.mp4", "insert.mp4"]


@pytest.mark.asyncio
async def test_packaged_timeline_mapping_reuses_local_normalized_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_calls: list[str] = []

    async def _fake_probe_media_duration(path: Path) -> float:
        probe_calls.append(path.name)
        if path.name == "intro.mp4":
            return 1.2
        if path.name == "insert.mp4":
            return 0.8
        raise AssertionError(f"unexpected probe path: {path}")

    monkeypatch.setattr("roughcut.pipeline.steps._probe_media_duration", _fake_probe_media_duration)
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_asset_plan",
        lambda _payload, _name: (_ for _ in ()).throw(AssertionError("should reuse local packaging payload")),
    )

    timeline_mapping = await _resolve_packaged_timeline_mapping_context(
        {
            "packaging": {
                "intro": {"path": "intro.mp4"},
                "insert": {"path": "insert.mp4", "insert_after_sec": 2.0},
            },
            "editing_accents": {
                "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
            },
        },
        keep_segments=[{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}],
    )

    assert timeline_mapping["intro_duration_sec"] == 1.2
    assert timeline_mapping["effective_insert_duration_sec"] == 0.8
    assert timeline_mapping["insert_after_sec"] == 3.2
    assert probe_calls == ["intro.mp4", "insert.mp4"]


@pytest.mark.asyncio
async def test_packaged_timeline_mapping_reuses_local_transitions_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def _capture_transition_offsets(_render_plan, *, keep_segments, transitions=None):
        observed["render_plan"] = _render_plan
        observed["keep_segments"] = keep_segments
        observed["transitions"] = transitions
        return [(3.0, 0.12)]

    monkeypatch.setattr(
        pipeline_steps_module,
        "_resolve_transition_overlap_offsets",
        _capture_transition_offsets,
    )

    timeline_mapping = await _resolve_packaged_timeline_mapping_context(
        {
            "editing_accents": {
                "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
            },
            "packaging": {},
        },
        keep_segments=[{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}],
    )

    assert timeline_mapping["transition_offsets"] == [(3.0, 0.12)]
    assert observed["render_plan"] is None
    assert observed["keep_segments"] == [{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}]
    assert observed["transitions"] == {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12}


@pytest.mark.asyncio
async def test_packaged_timeline_mapping_reuses_local_packaging_timeline_for_section_profile_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_packaging_timelines: list[dict[str, Any]] = []

    async def _fake_probe_media_duration(_path: Path) -> float:
        return 0.0

    def _capture_section_profile_context(
        _render_plan: dict[str, Any] | None,
        *,
        packaging_timeline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert isinstance(packaging_timeline, dict)
        captured_packaging_timelines.append(dict(packaging_timeline))
        return {"subtitles": {}, "timeline_analysis": {}}

    monkeypatch.setattr("roughcut.pipeline.steps._probe_media_duration", _fake_probe_media_duration)
    monkeypatch.setattr(
        pipeline_steps_module,
        "_packaged_subtitle_section_profile_context",
        _capture_section_profile_context,
    )

    timeline_mapping = await _resolve_packaged_timeline_mapping_context(
        {
            "packaging": {},
            "editing_accents": {
                "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
            },
            "subtitles": {"style": "clean_white"},
        },
        keep_segments=[{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}],
    )

    assert timeline_mapping["section_profile_context"] == {"subtitles": {}, "timeline_analysis": {}}
    captured_timeline = dict(captured_packaging_timelines[0])
    assert captured_timeline.pop("hyperframes")["schema"] == "roughcut.hyperframes.plan.v1"
    assert captured_timeline == {
        "timeline_analysis": {},
        "editing_skill": {},
        "section_choreography": {},
        "subtitles": {"style": "clean_white"},
        "packaging": {
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        "editing_accents": {
            "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
        },
    }


@pytest.mark.asyncio
async def test_packaged_timeline_mapping_reuses_passed_packaging_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_calls: list[str] = []
    observed: dict[str, Any] = {}

    async def _fake_probe_media_duration(path: Path) -> float:
        probe_calls.append(path.name)
        if path.name == "intro.mp4":
            return 1.2
        if path.name == "insert.mp4":
            return 0.8
        raise AssertionError(f"unexpected probe path: {path}")

    def _capture_transition_offsets(_render_plan, *, keep_segments, transitions=None):
        observed["render_plan"] = _render_plan
        observed["keep_segments"] = keep_segments
        observed["transitions"] = transitions
        return [(3.0, 0.12)]

    monkeypatch.setattr("roughcut.pipeline.steps._probe_media_duration", _fake_probe_media_duration)
    monkeypatch.setattr(
        pipeline_steps_module,
        "resolve_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse passed packaging context")),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_resolve_transition_overlap_offsets",
        _capture_transition_offsets,
    )

    timeline_mapping = await _resolve_packaged_timeline_mapping_context(
        None,
        keep_segments=[{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}],
        packaging_context={
            "packaging_timeline": {
                "timeline_analysis": {"hook_end_sec": 1.5},
                "subtitles": {"section_profiles": [{"role": "hook", "start_sec": 0.0, "end_sec": 1.5}]},
            },
            "assets": {
                "intro": {"path": "intro.mp4"},
                "insert": {"path": "insert.mp4", "insert_after_sec": 2.0},
            },
            "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
            "section_profile_context": {
                "subtitles": {"section_profiles": [{"role": "hook", "start_sec": 0.0, "end_sec": 1.5}]},
                "timeline_analysis": {"hook_end_sec": 1.5},
            },
        },
    )

    assert timeline_mapping["transition_offsets"] == [(3.0, 0.12)]
    assert timeline_mapping["intro_duration_sec"] == 1.2
    assert timeline_mapping["effective_insert_duration_sec"] == 0.8
    assert timeline_mapping["insert_after_sec"] == 3.2
    assert observed["render_plan"] is None
    assert observed["keep_segments"] == [{"start": 0.0, "end": 3.0}, {"start": 4.0, "end": 7.0}]
    assert observed["transitions"] == {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12}
    assert timeline_mapping["section_profile_context"] == {
        "subtitles": {"section_profiles": [{"role": "hook", "start_sec": 0.0, "end_sec": 1.5}]},
        "timeline_analysis": {"hook_end_sec": 1.5},
    }
    assert probe_calls == ["intro.mp4", "insert.mp4"]


@pytest.mark.asyncio
async def test_map_editing_accents_to_packaged_timeline_reuses_passed_timeline_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "_resolve_packaged_timeline_mapping_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse passed timeline mapping")),
    )

    mapped = await _map_editing_accents_to_packaged_timeline(
        {
            "emphasis_overlays": [{"start_time": 1.0, "end_time": 1.4, "text": "demo"}],
            "sound_effects": [{"start_time": 1.2, "duration_sec": 0.1, "frequency": 880}],
        },
        None,
        keep_segments=[{"start": 0.0, "end": 3.0}],
        timeline_mapping={
            "transition_offsets": [],
            "intro_duration_sec": 1.0,
            "insert_plan": None,
            "insert_after_sec": 0.0,
            "effective_insert_duration_sec": 0.0,
        },
    )

    assert mapped["emphasis_overlays"] == [{"start_time": 2.0, "end_time": 2.4, "text": "demo"}]
    assert mapped["sound_effects"] == [{"start_time": 2.2, "duration_sec": 0.1, "frequency": 880}]


@pytest.mark.asyncio
async def test_packaging_trailing_gap_allowance_reuses_shared_outro_duration_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe_calls: list[str] = []

    async def _fake_probe(path: Path) -> SimpleNamespace:
        probe_calls.append(path.name)
        return SimpleNamespace(duration=1.6)

    monkeypatch.setattr("roughcut.pipeline.steps.probe", _fake_probe)

    packaged_plan = {"packaging_timeline": {"packaging": {"outro": {"path": "shared-outro.mp4"}}}}
    ai_effect_plan = {"packaging_timeline": {"packaging": {"outro": {"path": "shared-outro.mp4"}}}}
    packaged_outro_plan = {"path": "shared-outro.mp4"}
    ai_effect_outro_plan = {"path": "shared-outro.mp4"}

    packaged_duration = await _resolve_packaging_trailing_gap_allowance(packaged_plan, outro_plan=packaged_outro_plan)
    ai_effect_duration = (
        packaged_duration
        if str((packaged_outro_plan or {}).get("path") or "").strip()
        == str((ai_effect_outro_plan or {}).get("path") or "").strip()
        else await _resolve_packaging_trailing_gap_allowance(ai_effect_plan, outro_plan=ai_effect_outro_plan)
    )

    assert packaged_duration == 1.6
    assert ai_effect_duration == 1.6
    assert probe_calls == ["shared-outro.mp4"]


@pytest.mark.asyncio
async def test_packaging_trailing_gap_allowance_reuses_passed_outro_plan_without_render_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_asset_plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should reuse provided outro plan")),
    )

    async def _fake_probe(path: Path) -> SimpleNamespace:
        return SimpleNamespace(duration=1.2 if path.name == "shared-outro.mp4" else 0.0)

    monkeypatch.setattr("roughcut.pipeline.steps.probe", _fake_probe)

    duration = await _resolve_packaging_trailing_gap_allowance(
        outro_plan={"path": "shared-outro.mp4"},
    )

    assert duration == 1.2


def test_resolve_packaged_render_variant_reuses_duration_driven_timeline_and_single_subtitle_source() -> None:
    subtitle_items = [{"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "hello"}]

    source_path, editorial_timeline, subtitles = _resolve_packaged_render_variant(
        original_source_path=Path("plain.mp4"),
        original_duration_sec=1.0,
        subtitle_items=subtitle_items,
    )
    assert source_path == Path("plain.mp4")
    assert editorial_timeline == {"segments": [{"type": "keep", "start": 0.0, "end": 1.0}]}
    assert subtitles == subtitle_items
    assert subtitles is not subtitle_items

    avatar_source_path, avatar_timeline, avatar_subtitles = _resolve_packaged_render_variant(
        original_source_path=Path("plain.mp4"),
        original_duration_sec=1.0,
        subtitle_items=subtitle_items,
        variant_source_path=Path("avatar.mp4"),
        variant_duration_sec=12.5,
    )
    assert avatar_source_path == Path("avatar.mp4")
    assert avatar_timeline == {"segments": [{"type": "keep", "start": 0.0, "end": 12.5}]}
    assert avatar_subtitles == subtitle_items
    assert avatar_subtitles is not subtitle_items


def test_manual_keep_segments_are_sorted_merged_and_clamped() -> None:
    segments = _normalize_manual_keep_segments(
        [
            {"start": 8.0, "end": 12.0},
            {"start": -1.0, "end": 2.0},
            {"start": 1.99, "end": 4.0},
            {"start": 14.0, "end": 14.02},
            {"start": 18.0, "end": 30.0},
        ],
        source_duration_sec=20.0,
    )

    assert segments == [
        {"start": 0.0, "end": 4.0},
        {"start": 8.0, "end": 12.0},
        {"start": 18.0, "end": 20.0},
    ]


def test_manual_keep_segments_heal_micro_cut_gaps() -> None:
    segments = _normalize_manual_keep_segments(
        [
            {"start": 0.0, "end": 10.0},
            {"start": 10.05, "end": 20.0},
            {"start": 20.2, "end": 30.0},
        ],
        source_duration_sec=40.0,
    )

    assert segments == [
        {"start": 0.0, "end": 20.0},
        {"start": 20.2, "end": 30.0},
    ]


def test_manual_editor_draft_subtitles_are_stale_after_subtitle_regeneration() -> None:
    draft_created_at = datetime(2026, 5, 15, 8, 0, 0, tzinfo=timezone.utc)
    latest_subtitle_created_at = draft_created_at + timedelta(seconds=1)

    assert _manual_editor_draft_subtitles_are_stale(
        draft_created_at=draft_created_at,
        latest_subtitle_created_at=latest_subtitle_created_at,
    )
    assert not _manual_editor_draft_subtitles_are_stale(
        draft_created_at=latest_subtitle_created_at,
        latest_subtitle_created_at=draft_created_at,
    )
    assert not _manual_editor_draft_subtitles_are_stale(
        draft_created_at=None,
        latest_subtitle_created_at=latest_subtitle_created_at,
    )


def test_manual_editor_subtitle_fingerprint_tracks_current_subtitle_baseline() -> None:
    baseline = [
        {"index": 0, "start_time": 1.6, "end_time": 8.0, "text_final": "今天终于收到了年前的最后的一个一款"},
        {"index": 1, "start_time": 8.0, "end_time": 13.813, "text_final": "小玩具也是耗尽了我这次的欧气啊"},
    ]
    changed = [
        {"index": 0, "start_time": 1.6, "end_time": 8.0, "text_final": "今天终于收到了年"},
        {"index": 1, "start_time": 8.0, "end_time": 13.813, "text_final": "前的最后的一个一款小玩具"},
    ]

    baseline_fingerprint = _manual_editor_subtitle_fingerprint(baseline)

    assert baseline_fingerprint
    assert baseline_fingerprint == _manual_editor_subtitle_fingerprint([dict(item) for item in baseline])
    assert baseline_fingerprint != _manual_editor_subtitle_fingerprint(changed)


def test_manual_editor_subtitle_overrides_require_matching_fingerprint() -> None:
    current_fingerprint = _manual_editor_subtitle_fingerprint(
        [{"index": 0, "start_time": 1.6, "end_time": 8.0, "text_final": "今天终于收到了年前的最后的一个一款"}]
    )
    assert current_fingerprint

    assert _manual_editor_draft_subtitles_match_fingerprint(
        {"base_subtitle_fingerprint": current_fingerprint},
        current_fingerprint,
    )
    assert not _manual_editor_draft_subtitles_match_fingerprint(
        {"base_subtitle_fingerprint": "old"},
        current_fingerprint,
    )
    assert _manual_editor_request_subtitles_match_fingerprint(
        ManualEditorApplyIn(base_subtitle_fingerprint=current_fingerprint),
        current_fingerprint,
    )
    assert not _manual_editor_request_subtitles_match_fingerprint(
        ManualEditorApplyIn(base_subtitle_fingerprint="old"),
        current_fingerprint,
    )


def test_manual_editor_rejects_stale_subtitle_revision_for_any_save() -> None:
    _validate_manual_editor_subtitle_revision(
        ManualEditorApplyIn(base_subtitle_fingerprint="current"),
        "current",
    )
    with pytest.raises(HTTPException) as exc_info:
        _validate_manual_editor_subtitle_revision(
            ManualEditorApplyIn(
                base_subtitle_fingerprint="old",
                keep_segments=[{"start": 0.0, "end": 10.0}],
            ),
            "current",
        )
    assert exc_info.value.status_code == 409
    assert "字幕数据已更新" in str(exc_info.value.detail)


def test_manual_editor_stored_projection_is_stale_after_subtitle_regeneration() -> None:
    current_fingerprint = "current"
    older_projection = datetime(2026, 5, 15, 8, 0, 0, tzinfo=timezone.utc)
    latest_subtitles = older_projection + timedelta(seconds=1)

    assert not _manual_editor_stored_projection_matches_subtitles(
        {"overrides": [{"index": 0, "text_final": "old"}]},
        current_subtitle_fingerprint=current_fingerprint,
        projection_created_at=older_projection,
        latest_subtitle_created_at=latest_subtitles,
    )
    assert _manual_editor_stored_projection_matches_subtitles(
        {"base_subtitle_fingerprint": current_fingerprint, "overrides": [{"index": 0, "text_final": "current"}]},
        current_subtitle_fingerprint=current_fingerprint,
        projection_created_at=older_projection,
        latest_subtitle_created_at=latest_subtitles,
    )
    assert not _manual_editor_stored_projection_matches_subtitles(
        {"base_subtitle_fingerprint": "old", "overrides": [{"index": 0, "text_final": "old"}]},
        current_subtitle_fingerprint=current_fingerprint,
        projection_created_at=latest_subtitles,
        latest_subtitle_created_at=older_projection,
    )


def test_manual_editor_timeline_records_and_matches_subtitle_fingerprint() -> None:
    payload = {
        "analysis": {
            "manual_editor": {
                "timeline_subtitle_fingerprint": "fingerprint-a",
                "source_subtitle_basis": "canonical_transcript",
            }
        }
    }

    assert _manual_editor_timeline_subtitle_fingerprint(payload) == "fingerprint-a"
    assert _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="fingerprint-a",
        current_timeline_subtitle_fingerprint="fingerprint-b",
        current_subtitle_basis="canonical_transcript",
        current_timeline_subtitle_basis="subtitle_item",
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert not _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="fingerprint-b",
        current_timeline_subtitle_fingerprint="fingerprint-c",
        current_subtitle_basis="subtitle_item",
        current_timeline_subtitle_basis="subtitle_projection",
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_manual_editor_timeline_matches_either_source_or_projection_fingerprint() -> None:
    payload = {"analysis": {"manual_editor": {"base_subtitle_fingerprint": "source-current"}}}

    assert _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="source-current",
        current_timeline_subtitle_fingerprint="projection-current",
        current_subtitle_basis="canonical_transcript",
        current_timeline_subtitle_basis="subtitle_item",
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert _manual_editor_timeline_matches_current_subtitles(
        {"analysis": {"manual_editor": {"timeline_subtitle_fingerprint": "projection-current"}}},
        current_subtitle_fingerprint="source-current",
        current_timeline_subtitle_fingerprint="projection-current",
        current_subtitle_basis="canonical_transcript",
        current_timeline_subtitle_basis="subtitle_item",
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )


def test_manual_editor_timeline_accepts_newer_timeline_even_when_subtitle_representation_differs() -> None:
    payload = {
        "analysis": {
            "manual_editor": {
                "timeline_subtitle_fingerprint": "decision-fingerprint",
                "decision_subtitle_basis": "transcript_segment",
                "source_subtitle_basis": "transcript_segment",
            }
        }
    }

    assert _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="aligned-source-fingerprint",
        current_timeline_subtitle_fingerprint="subtitle-item-fingerprint",
        current_subtitle_basis="transcript_segment",
        current_timeline_subtitle_basis="subtitle_item",
        timeline_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="aligned-source-fingerprint",
        current_timeline_subtitle_fingerprint="subtitle-item-fingerprint",
        current_subtitle_basis="subtitle_item",
        current_timeline_subtitle_basis="subtitle_projection",
        timeline_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_manual_editor_timeline_accepts_canonical_refresh_basis_as_canonical_family() -> None:
    payload = {
        "analysis": {
            "manual_editor": {
                "timeline_subtitle_fingerprint": "decision-fingerprint",
                "source_subtitle_basis": "canonical_refresh",
            }
        }
    }

    assert _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="aligned-source-fingerprint",
        current_timeline_subtitle_fingerprint="subtitle-item-fingerprint",
        current_subtitle_basis="canonical_transcript",
        current_timeline_subtitle_basis="subtitle_item",
        timeline_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_manual_editor_legacy_timeline_is_stale_when_subtitle_revision_is_newer() -> None:
    timeline_created_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    assert not _manual_editor_timeline_matches_current_subtitles(
        {"analysis": {}},
        current_subtitle_fingerprint="fingerprint-a",
        current_subtitle_basis="canonical_transcript",
        timeline_created_at=timeline_created_at,
        latest_subtitle_revision_created_at=timeline_created_at + timedelta(seconds=1),
    )
    assert _manual_editor_timeline_matches_current_subtitles(
        {"analysis": {}},
        current_subtitle_fingerprint="fingerprint-a",
        current_subtitle_basis="canonical_transcript",
        timeline_created_at=timeline_created_at,
        latest_subtitle_revision_created_at=timeline_created_at - timedelta(seconds=1),
    )


def test_manual_keep_segments_from_editorial_payload_heals_legacy_micro_cuts() -> None:
    segments = _manual_keep_segments_from_editorial_payload(
        {
            "segments": [
                {"type": "keep", "start": 0.0, "end": 10.0},
                {"type": "cut", "start": 10.0, "end": 10.05, "reason": "filler_word"},
                {"type": "keep", "start": 10.05, "end": 20.0},
                {"type": "cut", "start": 20.0, "end": 20.2, "reason": "manual_editor_removed"},
                {"type": "keep", "start": 20.2, "end": 30.0},
            ]
        }
    )

    assert segments == [
        {"start": 0.0, "end": 20.0},
        {"start": 20.2, "end": 30.0},
    ]


def test_manual_editor_base_keep_segments_ignore_manual_refine_override_for_editor_baseline() -> None:
    editorial_payload = {
        "segments": [
            {"type": "keep", "start": 1.0, "end": 3.0},
            {"type": "cut", "start": 3.0, "end": 5.0, "reason": "silence"},
            {"type": "keep", "start": 5.0, "end": 6.5},
        ]
    }
    refine_payload = {
        "schema": "refine_decision_plan.v1",
        "mode": "manual_refine",
        "editorial_timeline_id": "timeline-1",
        "editorial_timeline_version": 2,
        "keep_segments": [{"start": 0.0, "end": 8.0}],
    }

    assert _manual_editor_base_keep_segment_dicts(
        editorial_payload,
        refine_plan_payload=refine_payload,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=2,
        source_duration_sec=8.0,
        prefer_refine_plan=False,
    ) == [
        {"start": 1.0, "end": 3.0},
        {"start": 5.0, "end": 6.5},
    ]

    assert _manual_editor_base_keep_segment_dicts(
        editorial_payload,
        refine_plan_payload=refine_payload,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=2,
        source_duration_sec=8.0,
        prefer_refine_plan=True,
    ) == [{"start": 0.0, "end": 8.0}]


def test_manual_keep_segments_expand_to_full_editorial_timeline() -> None:
    payload = _build_editorial_segments_from_keep_segments(
        [
            {"start": 1.0, "end": 3.0},
            {"start": 5.0, "end": 6.5},
        ],
        source_duration_sec=8.0,
    )

    assert payload == [
        {"start": 0.0, "end": 1.0, "type": "cut", "reason": "manual_editor_removed"},
        {"start": 1.0, "end": 3.0, "type": "keep", "reason": "manual_editor_keep"},
        {"start": 3.0, "end": 5.0, "type": "cut", "reason": "manual_editor_removed"},
        {"start": 5.0, "end": 6.5, "type": "keep", "reason": "manual_editor_keep"},
        {"start": 6.5, "end": 8.0, "type": "cut", "reason": "manual_editor_removed"},
    ]


def test_manual_editor_packaging_plan_reads_nested_packaging_timeline() -> None:
    assert _manual_editor_packaging_plan_from_render_plan(
        {
            "packaging_timeline": {
                "subtitles": {"style": "clean_white", "motion_style": "motion_slide"},
                "packaging": {
                    "intro": {"path": "intro.mp4"},
                    "insert": {"asset_id": "insert-a", "path": "insert.mp4", "insert_target_duration_sec": 1.23456},
                    "music": {"path": "music.mp3"},
                },
                "editing_accents": {"style": "smart_effect_punch"},
            },
            "cover": {"style": "hero", "title_style": "strong"},
            "delivery": {"resolution_mode": "preset", "resolution_preset": "1080p"},
        }
    ) == {
        "subtitle_style": "clean_white",
        "subtitle_motion_style": "motion_slide",
        "smart_effect_style": "smart_effect_punch",
        "intro": {"path": "intro.mp4"},
        "outro": None,
        "insert": {
            "asset_id": "insert-a",
            "path": "insert.mp4",
            "insert_target_duration_sec": 1.235,
            "candidate_assets": [
                {
                    "asset_id": "insert-a",
                    "path": "insert.mp4",
                    "original_name": "",
                    "insert_archetype": "",
                    "insert_motion_profile": "",
                    "insert_transition_style": "",
                    "insert_target_duration_sec": 1.235,
                    "selection_score": 0.0,
                    "selection_reasons": [],
                }
            ],
        },
        "watermark": None,
        "music": {
            "path": "music.mp3",
            "audio_cues": [
                {
                    "kind": "bgm_entry",
                    "time_sec": 0.0,
                    "reason": "",
                    "review_recommended": False,
                }
            ],
        },
        "export_resolution_mode": "preset",
        "export_resolution_preset": "1080p",
        "export_frame_rate_mode": "source",
        "export_frame_rate_preset": "30",
    }


def test_manual_editor_packaging_plan_reuses_local_normalized_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_render_plan_context",
        lambda _payload: {
            "packaging_timeline": {
                "subtitles": {"style": "clean_white", "motion_style": "motion_slide"},
                "packaging": {
                    "intro": {"path": "shared-intro.mp4"},
                    "insert": {"asset_id": "shared-insert", "path": "shared-insert.mp4"},
                    "music": {"path": "shared-music.mp3"},
                },
                "editing_accents": {"style": "smart_effect_punch"},
            },
            "delivery": {},
        },
    )

    assert _manual_editor_packaging_plan_from_render_plan(
        {
            "packaging_timeline": {
                "subtitles": {"style": "clean_white", "motion_style": "motion_slide"},
                "packaging": {
                    "intro": {"path": "shared-intro.mp4"},
                    "insert": {"asset_id": "shared-insert", "path": "shared-insert.mp4"},
                    "music": {"path": "shared-music.mp3"},
                },
                "editing_accents": {"style": "smart_effect_punch"},
            },
        }
    ) == {
        "subtitle_style": "clean_white",
        "subtitle_motion_style": "motion_slide",
        "smart_effect_style": "smart_effect_punch",
        "intro": {"path": "shared-intro.mp4"},
        "outro": None,
        "insert": {
            "asset_id": "shared-insert",
            "path": "shared-insert.mp4",
            "candidate_assets": [
                {
                    "asset_id": "shared-insert",
                    "path": "shared-insert.mp4",
                    "original_name": "",
                    "insert_archetype": "",
                    "insert_motion_profile": "",
                    "insert_transition_style": "",
                    "insert_target_duration_sec": 0.0,
                    "selection_score": 0.0,
                    "selection_reasons": [],
                }
            ],
        },
        "watermark": None,
        "music": {
            "path": "shared-music.mp3",
            "audio_cues": [
                {
                    "kind": "bgm_entry",
                    "time_sec": 0.0,
                    "reason": "",
                    "review_recommended": False,
                }
            ],
        },
        "export_resolution_mode": "source",
        "export_resolution_preset": "1080p",
        "export_frame_rate_mode": "source",
        "export_frame_rate_preset": "30",
    }


def test_manual_editor_packaging_plan_reuses_caller_render_plan_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_render_plan_context",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse caller render plan context")),
    )

    assert _manual_editor_packaging_plan_from_render_plan(
        None,
        render_plan_context={
            "packaging_timeline": {
                "subtitles": {"style": "clean_white", "motion_style": "motion_slide"},
                "packaging": {"intro": {"path": "shared-intro.mp4"}},
                "editing_accents": {"style": "smart_effect_punch"},
            },
            "delivery": {"resolution_mode": "preset", "resolution_preset": "1080p"},
        },
    ) == {
        "subtitle_style": "clean_white",
        "subtitle_motion_style": "motion_slide",
        "smart_effect_style": "smart_effect_punch",
        "intro": {"path": "shared-intro.mp4"},
        "outro": None,
        "insert": None,
        "watermark": None,
        "music": None,
        "export_resolution_mode": "preset",
        "export_resolution_preset": "1080p",
        "export_frame_rate_mode": "source",
        "export_frame_rate_preset": "30",
    }


def test_manual_editor_packaging_plan_reuses_caller_packaging_timeline_and_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_render_plan_context",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse caller packaging timeline / delivery")),
    )

    assert _manual_editor_packaging_plan_from_render_plan(
        None,
        packaging_timeline={
            "subtitles": {"style": "clean_white", "motion_style": "motion_slide"},
            "packaging": {"intro": {"path": "shared-intro.mp4"}},
            "editing_accents": {"style": "smart_effect_punch"},
        },
        delivery={"resolution_mode": "preset", "resolution_preset": "1080p"},
    ) == {
        "subtitle_style": "clean_white",
        "subtitle_motion_style": "motion_slide",
        "smart_effect_style": "smart_effect_punch",
        "intro": {"path": "shared-intro.mp4"},
        "outro": None,
        "insert": None,
        "watermark": None,
        "music": None,
        "export_resolution_mode": "preset",
        "export_resolution_preset": "1080p",
        "export_frame_rate_mode": "source",
        "export_frame_rate_preset": "30",
    }


def test_packaging_timeline_assets_accept_normalized_payload_directly() -> None:
    assert packaging_timeline_assets(
        {
            "subtitles": {"style": "clean_white"},
            "packaging": {
                "intro": {"path": "intro.mp4"},
                "music": {"path": "music.mp3"},
            },
            "editing_accents": {"style": "smart_effect_punch"},
        }
    ) == {
        "intro": {"path": "intro.mp4"},
        "outro": None,
        "insert": None,
        "watermark": None,
        "music": {
            "path": "music.mp3",
            "audio_cues": [
                {
                    "kind": "bgm_entry",
                    "time_sec": 0.0,
                    "reason": "",
                    "review_recommended": False,
                }
            ],
        },
    }


def test_packaging_timeline_asset_plan_accepts_nested_and_normalized_payloads() -> None:
    assert packaging_timeline_asset_plan(
        {
            "packaging_timeline": {
                "packaging": {
                    "outro": {"path": "outro.mp4"},
                }
            }
        },
        "outro",
    ) == {"path": "outro.mp4"}
    assert packaging_timeline_asset_plan(
        {
            "packaging": {
                "music": {"path": "music.mp3"},
            }
        },
        "music",
    ) == {
        "path": "music.mp3",
        "audio_cues": [
            {
                "kind": "bgm_entry",
                "time_sec": 0.0,
                "reason": "",
                "review_recommended": False,
            }
        ],
    }


def test_packaging_timeline_asset_plan_returns_safe_copy() -> None:
    payload = {
        "packaging": {
            "intro": {"path": "intro.mp4", "gain_db": -6.0},
        }
    }

    intro_plan = packaging_timeline_asset_plan(payload, "intro")
    intro_plan["gain_db"] = -12.0

    assert packaging_timeline_asset_plan(payload, "intro") == {"path": "intro.mp4", "gain_db": -6.0}
    assert packaging_timeline_asset_plan(payload, "") is None
    assert packaging_timeline_asset_plan(None, "intro") is None


def test_packaging_timeline_asset_plan_reuses_local_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import packaging_timeline as packaging_timeline_module

    monkeypatch.setattr(
        packaging_timeline_module,
        "packaging_timeline_assets",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local packaging payload")),
    )

    assert packaging_timeline_asset_plan(
        {
            "packaging": {
                "music": {"path": "music.mp3"},
            }
        },
        "music",
    ) == {
        "path": "music.mp3",
        "audio_cues": [
            {
                "kind": "bgm_entry",
                "time_sec": 0.0,
                "reason": "",
                "review_recommended": False,
            }
        ],
    }


def test_packaging_timeline_transitions_accept_nested_and_normalized_payloads() -> None:
    assert packaging_timeline_transitions(
        {
            "packaging_timeline": {
                "editing_accents": {
                    "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
                }
            }
        }
    ) == {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12}
    assert packaging_timeline_transitions(
        {
            "editing_accents": {
                "transitions": {"enabled": False, "boundary_indexes": [], "duration_sec": 0.2},
            }
        }
    ) == {"enabled": False, "boundary_indexes": [], "duration_sec": 0.2}


def test_packaging_timeline_transitions_returns_safe_copy() -> None:
    payload = {
        "editing_accents": {
            "transitions": {"enabled": True, "boundary_indexes": [1], "duration_sec": 0.16},
        }
    }

    transitions = packaging_timeline_transitions(payload)
    transitions["boundary_indexes"].append(2)
    transitions["duration_sec"] = 0.24

    assert packaging_timeline_transitions(payload) == {
        "enabled": True,
        "boundary_indexes": [1],
        "duration_sec": 0.16,
    }
    assert packaging_timeline_transitions({}) == {}
    assert packaging_timeline_transitions(None) == {}


def test_packaging_timeline_transitions_reuse_local_accents_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import packaging_timeline as packaging_timeline_module

    monkeypatch.setattr(
        packaging_timeline_module,
        "packaging_timeline_editing_accents",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local editing accents payload")),
    )

    assert packaging_timeline_transitions(
        {
            "editing_accents": {
                "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
            }
        }
    ) == {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12}


def test_packaging_timeline_presence_helpers_support_nested_and_normalized_payloads() -> None:
    nested_payload = {
        "packaging_timeline": {
            "packaging": {
                "intro": {"path": "intro.mp4"},
            },
            "editing_accents": {
                "transitions": {"boundary_indexes": [0]},
            },
        }
    }
    normalized_payload = {
        "packaging": {
            "music": {"path": "music.mp3"},
        },
        "editing_accents": {
            "emphasis_overlays": [{"start_time": 0.5, "end_time": 1.0, "text": "demo"}],
        },
    }

    assert packaging_timeline_has_packaging_assets(nested_payload) is True
    assert packaging_timeline_has_editing_accents(nested_payload) is True
    assert packaging_timeline_has_packaging_assets(normalized_payload) is True
    assert packaging_timeline_has_editing_accents(normalized_payload) is True


def test_packaging_timeline_presence_helpers_default_false_for_empty_payloads() -> None:
    assert packaging_timeline_has_packaging_assets({}) is False
    assert packaging_timeline_has_packaging_assets(None) is False
    assert packaging_timeline_has_editing_accents({}) is False
    assert packaging_timeline_has_editing_accents(
        {"packaging_timeline": {"editing_accents": {"transitions": {"boundary_indexes": []}}}}
    ) is False


def test_packaging_timeline_has_packaging_assets_reuses_local_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import packaging_timeline as packaging_timeline_module

    monkeypatch.setattr(
        packaging_timeline_module,
        "packaging_timeline_assets",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local packaging payload")),
    )

    assert packaging_timeline_has_packaging_assets(
        {
            "packaging": {
                "intro": {"path": "intro.mp4"},
            }
        }
    ) is True


def test_packaging_timeline_has_editing_accents_reuses_local_accents_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import packaging_timeline as packaging_timeline_module

    monkeypatch.setattr(
        packaging_timeline_module,
        "packaging_timeline_transitions",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local accents transitions")),
    )

    assert packaging_timeline_has_editing_accents(
        {
            "editing_accents": {
                "transitions": {"boundary_indexes": [0]},
            }
        }
    ) is True


def test_subtitle_section_profile_for_time_reads_nested_packaging_timeline_payload() -> None:
    assert _subtitle_section_profile_for_time(
        {
            "packaging_timeline": {
                "subtitles": {
                    "section_profiles": [
                        {"role": "hook", "start_sec": 0.0, "end_sec": 2.0},
                    ]
                }
            }
        },
        1.0,
    ) == {"role": "hook", "start_sec": 0.0, "end_sec": 2.0}


def test_subtitle_section_profile_for_time_reuses_local_normalized_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_subtitles",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local subtitles payload")),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_analysis",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local timeline_analysis payload")),
    )

    assert _subtitle_section_profile_for_time(
        {
            "subtitles": {
                "section_profiles": [
                    {"role": "hook", "start_sec": 0.0, "end_sec": 2.0},
                ]
            },
            "timeline_analysis": {
                "section_directives": [
                    {"role": "bridge", "start_sec": 2.0, "end_sec": 4.0},
                ]
            },
        },
        3.0,
    ) == {"role": "bridge", "start_sec": 2.0, "end_sec": 4.0}


def test_subtitle_section_profile_for_time_reuses_shared_section_profile_context_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "resolve_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should resolve section profile context via shared helper")),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_packaged_subtitle_section_profile_context",
        lambda _render_plan: {
            "subtitles": {
                "section_profiles": [
                    {"role": "hook", "start_sec": 0.0, "end_sec": 1.2},
                ]
            },
            "timeline_analysis": {},
        },
    )

    assert _subtitle_section_profile_for_time({}, 0.8) == {
        "role": "hook",
        "start_sec": 0.0,
        "end_sec": 1.2,
    }


def test_rewrite_packaged_subtitle_copy_reuses_local_section_profile_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_contexts: list[dict[str, Any]] = []

    def _capture_profile(
        _render_plan: dict[str, Any],
        _time_sec: float,
        *,
        section_profile_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        assert _render_plan is None
        assert isinstance(section_profile_context, dict)
        captured_contexts.append(section_profile_context)
        return None

    monkeypatch.setattr(
        pipeline_steps_module,
        "_subtitle_section_profile_for_time",
        _capture_profile,
    )

    rewritten = _rewrite_packaged_subtitle_copy(
        [
            {"start_time": 0.0, "end_time": 1.0, "text_final": "第一句"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "第二句"},
        ],
        render_plan={"packaging_timeline": {"subtitles": {"section_profiles": []}}},
    )

    assert [item["text_final"] for item in rewritten] == ["第一句", "第二句"]
    assert len(captured_contexts) == 2
    assert captured_contexts[0] is captured_contexts[1]


def test_rewrite_packaged_subtitle_copy_preserves_spoken_text_by_default() -> None:
    rewritten = _rewrite_packaged_subtitle_copy(
        [
            {
                "start_time": 0.0,
                "end_time": 3.0,
                "text_final": "今天我们看一下这个包的外挂点和快拆肩带。",
            }
        ],
        section_profile_context={
            "subtitles": {
                "section_profiles": [
                    {"role": "hook", "start_sec": 0.0, "end_sec": 4.0},
                ]
            }
        },
    )

    assert rewritten[0]["text_final"] == "今天我们看一下这个包的外挂点和快拆肩带。"
    assert rewritten[0]["subtitle_section_role"] == "hook"
    assert "text_original_final" not in rewritten[0]


def test_resegment_packaged_subtitles_reuses_local_section_profile_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_contexts: list[dict[str, Any]] = []

    def _capture_profile(
        _render_plan: dict[str, Any],
        _time_sec: float,
        *,
        section_profile_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        assert _render_plan is None
        assert isinstance(section_profile_context, dict)
        captured_contexts.append(section_profile_context)
        return None

    monkeypatch.setattr(
        pipeline_steps_module,
        "_subtitle_section_profile_for_time",
        _capture_profile,
    )

    resegmented = _resegment_packaged_subtitles(
        [
            {"start_time": 0.0, "end_time": 1.0, "text_final": "第一句"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "第二句"},
        ],
        render_plan={"packaging_timeline": {"subtitles": {"section_profiles": []}}},
    )

    assert [item["text_final"] for item in resegmented] == ["第一句", "第二句"]
    assert len(captured_contexts) == 2
    assert captured_contexts[0] is captured_contexts[1]


def test_resegment_packaged_subtitles_preserves_asr_timing_by_default() -> None:
    source = {
        "start_time": 10.0,
        "end_time": 13.4,
        "text_final": "这个肩带调节完以后背起来会更贴。",
        "text_original_final": "这个肩带调节完以后背起来会更贴，所以这个地方我觉得是重点。",
        "subtitle_copy_strategy": "detail_focus",
    }

    resegmented = _resegment_packaged_subtitles(
        [source],
        section_profile_context={
            "subtitles": {
                "section_profiles": [
                    {"role": "detail", "start_sec": 0.0, "end_sec": 20.0},
                ]
            }
        },
    )

    assert len(resegmented) == 1
    assert resegmented[0]["start_time"] == 10.0
    assert resegmented[0]["end_time"] == 13.4
    assert resegmented[0]["text_final"] == source["text_final"]


def test_stabilize_render_subtitle_timeline_extends_short_flash_without_reordering() -> None:
    stabilized = _stabilize_render_subtitle_timeline(
        [
            {"index": 0, "start_time": 1.0, "end_time": 1.12, "text_final": "FXX1"},
            {"index": 1, "start_time": 2.0, "end_time": 3.0, "text_final": "后一句正常"},
        ]
    )

    assert stabilized[0]["start_time"] == 1.0
    assert stabilized[0]["end_time"] == 1.82
    assert stabilized[0]["subtitle_timing_repair"] == "extend_short_flash"
    assert stabilized[1]["start_time"] == 2.0


def test_stabilize_render_subtitle_timeline_merges_short_flash_when_no_room_to_extend() -> None:
    stabilized = _stabilize_render_subtitle_timeline(
        [
            {"index": 0, "start_time": 1.0, "end_time": 1.12, "text_final": "短"},
            {"index": 1, "start_time": 1.14, "end_time": 2.0, "text_final": "后一句"},
        ]
    )

    assert len(stabilized) == 1
    assert stabilized[0]["text_final"] == "短后一句"
    assert stabilized[0]["start_time"] == 1.0
    assert stabilized[0]["end_time"] == 2.0


def test_stabilize_render_subtitle_timeline_coalesces_dense_high_cps_window() -> None:
    stabilized = _stabilize_render_subtitle_timeline(
        [
            {"index": 0, "start_time": 10.00, "end_time": 10.62, "text_final": "但我觉得一般不需要一般"},
            {"index": 1, "start_time": 10.62, "end_time": 11.45, "text_final": "不需要好那么当你适应了这个"},
            {"index": 2, "start_time": 11.48, "end_time": 12.30, "text_final": "你看这次我就摁错了"},
            {"index": 3, "start_time": 12.32, "end_time": 13.10, "text_final": "这个小揪揪了"},
            {"index": 4, "start_time": 13.12, "end_time": 13.70, "text_final": "以后啊就是说你要去摁"},
            {"index": 5, "start_time": 13.72, "end_time": 14.30, "text_final": "住这两头啊"},
            {"index": 6, "start_time": 14.32, "end_time": 15.00, "text_final": "去进行调整"},
        ]
    )

    assert len(stabilized) <= 5
    assert all(
        float(item["end_time"]) - float(item["start_time"]) >= 0.82
        for item in stabilized
        if item.get("packaged_subtitle_merge") != "dense_subtitle_window_pacing"
    )
    assert any(item.get("packaged_subtitle_merge") == "subtitle_readability_pacing" for item in stabilized)


def test_stabilize_render_subtitle_timeline_spreads_unmergeable_dense_flash_run() -> None:
    stabilized = _stabilize_render_subtitle_timeline(
        [
            {"index": 0, "start_time": 401.432, "end_time": 401.512, "text_final": "你看只能调节这个这边就是说固"},
            {"index": 1, "start_time": 401.512, "end_time": 401.593, "text_final": "那就先调节这边然后这样一点一般不需要"},
            {"index": 2, "start_time": 401.593, "end_time": 401.738, "text_final": "不需要好那么当你适应了这个"},
            {"index": 3, "start_time": 401.738, "end_time": 401.752, "text_final": "要按"},
            {"index": 4, "start_time": 401.752, "end_time": 401.841, "text_final": "这个小揪揪了以后啊就是说你要去摁"},
            {"index": 5, "start_time": 401.841, "end_time": 401.913, "text_final": "住这两头啊去进行调整"},
            {"index": 6, "start_time": 401.913, "end_time": 406.473, "text_final": "就是说它可能会有一个小扣"},
            {"index": 7, "start_time": 406.473, "end_time": 410.713, "text_final": "然后你要弄懂这个安装方法"},
        ]
    )

    durations = [
        float(item["end_time"]) - float(item["start_time"])
        for item in stabilized
    ]
    assert min(durations) >= 0.22
    max_events_per_one_sec = 0
    for index, item in enumerate(stabilized):
        start = float(item["start_time"])
        count = sum(
            1
            for cursor in range(index, len(stabilized))
            if float(stabilized[cursor]["start_time"]) < start + 1.0
        )
        max_events_per_one_sec = max(max_events_per_one_sec, count)
    assert max_events_per_one_sec < 4
    assert any(item.get("subtitle_timing_repair") == "spread_dense_subtitle_run" for item in stabilized)


def test_stabilize_render_subtitle_timeline_extends_residual_short_flash_and_shifts_following() -> None:
    stabilized = _stabilize_render_subtitle_timeline(
        [
            {
                "index": 0,
                "start_time": 404.024,
                "end_time": 405.023,
                "text_final": "前面一句也很长很长不能继续合并否则会超过字幕长度限制并且这句话本身已经足够长",
            },
            {"index": 1, "start_time": 405.023, "end_time": 405.120, "text_final": "要按"},
            {
                "index": 2,
                "start_time": 405.160,
                "end_time": 405.764,
                "text_final": "后面一句很长很长所以不能简单合并否则显示会超过字幕长度限制而且会破坏阅读节奏",
            },
        ]
    )

    assert stabilized[1]["start_time"] == 405.023
    assert stabilized[1]["end_time"] - stabilized[1]["start_time"] >= 0.22
    assert stabilized[1]["subtitle_timing_repair"] in {
        "extend_residual_short_flash",
        "extend_short_flash",
        "spread_dense_subtitle_run",
    }
    assert stabilized[2]["start_time"] >= stabilized[1]["end_time"]


def test_render_subtitle_global_offset_estimator_requires_stable_drift() -> None:
    audit = {
        "events": [
            {
                "matched": True,
                "text": f"测试字幕{index}",
                "subtitle_start_sec": float(index * 3),
                "expected_start_sec": float(index * 3) + 8.42 + (0.05 if index % 2 else 0.0),
            }
            for index in range(12)
        ]
    }

    estimate = _estimate_render_subtitle_global_offset(audit)

    assert estimate["stable"] is True
    assert estimate["offset_sec"] == pytest.approx(8.445, abs=0.01)


def test_render_subtitle_global_offset_estimator_rejects_unstable_drift() -> None:
    audit = {
        "events": [
            {
                "matched": True,
                "text": f"测试字幕{index}",
                "subtitle_start_sec": float(index * 3),
                "expected_start_sec": float(index * 3) + (0.2 if index % 2 else 4.5),
            }
            for index in range(12)
        ]
    }

    estimate = _estimate_render_subtitle_global_offset(audit)

    assert estimate["stable"] is False


def test_shift_render_subtitle_items_moves_words_with_subtitle_bounds() -> None:
    shifted = _shift_render_subtitle_items(
        [
            {
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "测试",
                "words": [{"word": "测", "start": 1.0, "end": 1.4}, {"word": "试", "start": 1.4, "end": 2.0}],
            }
        ],
        offset_sec=8.42,
    )

    assert shifted[0]["start_time"] == pytest.approx(9.42)
    assert shifted[0]["end_time"] == pytest.approx(10.42)
    assert shifted[0]["words"][0]["start"] == pytest.approx(9.42)
    assert shifted[0]["words"][1]["end"] == pytest.approx(10.42)
    assert shifted[0]["render_asr_timing_repair"] == "global_offset"


def test_retime_render_subtitle_items_from_alignment_audit_uses_expected_asr_bounds() -> None:
    repaired, summary = _retime_render_subtitle_items_from_alignment_audit(
        [
            {
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "测试字幕",
                "words": [{"word": "测试", "start": 1.0, "end": 1.5}, {"word": "字幕", "start": 1.5, "end": 2.0}],
            }
        ],
        {
            "events": [
                {
                    "matched": True,
                    "text": "测试字幕",
                    "subtitle_start_sec": 1.0,
                    "subtitle_end_sec": 2.0,
                    "expected_start_sec": 9.0,
                    "expected_end_sec": 10.0,
                }
            ]
        },
        duration_sec=20.0,
    )

    assert summary["repair_mode"] == "rendered_audio_forced_alignment"
    assert repaired[0]["start_time"] == pytest.approx(8.96)
    assert repaired[0]["end_time"] == pytest.approx(10.12)
    assert repaired[0]["words"][0]["start"] == pytest.approx(8.96)
    assert repaired[0]["words"][1]["end"] == pytest.approx(10.12)


def test_retime_render_subtitle_items_drops_fallback_events_past_render_duration() -> None:
    repaired, summary = _retime_render_subtitle_items_from_alignment_audit(
        [
            {"start_time": 0.0, "end_time": 1.0, "text_final": "匹配字幕"},
            {"start_time": 18.0, "end_time": 20.0, "text_final": "尾部字幕"},
        ],
        {
            "events": [
                {
                    "matched": True,
                    "text": "匹配字幕",
                    "subtitle_start_sec": 0.0,
                    "subtitle_end_sec": 1.0,
                    "expected_start_sec": 8.0,
                    "expected_end_sec": 9.0,
                },
                {
                    "matched": False,
                    "subtitle_start_sec": 18.0,
                    "subtitle_end_sec": 20.0,
                },
            ]
        },
        duration_sec=10.0,
    )

    assert [item["text_final"] for item in repaired] == ["匹配字幕"]
    assert repaired[0]["end_time"] <= 10.0
    assert summary["out_of_bounds_dropped_count"] == 1
    assert summary["fallback_retimed_count"] == 1


def test_bound_render_subtitles_to_duration_clamps_variant_sidecar_tail() -> None:
    bounded = _bound_render_subtitles_to_duration(
        [
            {"start_time": 16.28, "end_time": 21.72, "text_final": "第一条"},
            {"start_time": 23.56, "end_time": 24.38, "text_final": "第二条"},
            {"start_time": 25.0, "end_time": 26.0, "text_final": "越界"},
        ],
        duration_sec=24.021,
    )

    assert [item["text_final"] for item in bounded] == ["第一条", "第二条"]
    assert bounded[-1]["end_time"] == pytest.approx(23.981)
    assert bounded[-1]["render_duration_bound_repair"] == "clamp_to_variant_duration"


def test_render_subtitle_alignment_gate_blocks_large_bad_drift_ratio() -> None:
    assert not _render_subtitle_alignment_gate_passes(
        {
            "event_count": 10,
            "matched_count": 10,
            "unmatched_count": 0,
            "bad_drift_count": 8,
            "avg_abs_start_drift_sec": 8.0,
            "avg_abs_end_drift_sec": 8.0,
        }
    )


def test_render_subtitle_alignment_gate_blocks_tail_bad_cluster_despite_clean_average() -> None:
    events: list[dict[str, Any]] = []
    for index in range(35):
        events.append(
            {
                "matched": True,
                "bad_drift": False,
                "subtitle_start_sec": float(index * 8),
                "subtitle_end_sec": float(index * 8 + 2),
                "start_drift_sec": 0.04,
                "end_drift_sec": 0.04,
            }
        )
    for index in range(5):
        events.append(
            {
                "matched": index % 2 == 0,
                "bad_drift": index % 2 == 0,
                "subtitle_start_sec": 320.0 + index * 0.9,
                "subtitle_end_sec": 320.7 + index * 0.9,
                "start_drift_sec": 3.2 if index % 2 == 0 else None,
                "end_drift_sec": 0.2 if index % 2 == 0 else None,
            }
        )
    audit = {
        "event_count": 40,
        "matched_count": 37,
        "unmatched_count": 3,
        "bad_drift_count": 5,
        "avg_abs_start_drift_sec": 0.32,
        "avg_abs_end_drift_sec": 0.2,
        "events": events,
    }

    metrics = _render_subtitle_alignment_local_cluster_metrics(audit)

    assert metrics["tail_bad_count"] == 5
    assert metrics["worst_window_count"] == 5
    assert not metrics["gate_pass"]
    assert not _render_subtitle_alignment_gate_passes(audit)


def test_render_subtitle_alignment_gate_allows_single_isolated_short_sample_bad_event() -> None:
    events = [
        {
            "matched": True,
            "bad_drift": False,
            "subtitle_start_sec": float(index * 4),
            "subtitle_end_sec": float(index * 4 + 2),
            "start_drift_sec": 0.04,
            "end_drift_sec": 0.12,
        }
        for index in range(5)
    ]
    events.append(
        {
            "matched": False,
            "bad_drift": True,
            "subtitle_start_sec": 26.927,
            "subtitle_end_sec": 27.747,
            "start_drift_sec": 0.0,
            "end_drift_sec": 0.0,
        }
    )
    audit = {
        "event_count": 6,
        "matched_count": 5,
        "unmatched_count": 1,
        "bad_drift_count": 1,
        "avg_abs_start_drift_sec": 0.04,
        "avg_abs_end_drift_sec": 0.088,
        "events": events,
    }

    metrics = _render_subtitle_alignment_local_cluster_metrics(audit)

    assert metrics["gate_pass"] is True
    assert _render_subtitle_alignment_gate_passes(audit) is True


def test_drop_clustered_unmatched_render_subtitles_keeps_matched_bad_rows_for_retime() -> None:
    subtitle_items = [
        {"start_time": float(index), "end_time": float(index) + 0.8, "text_final": f"字幕{index}"}
        for index in range(6)
    ]
    audit = {
        "events": [
            {"matched": True, "bad_drift": False, "subtitle_start_sec": 0.0, "subtitle_end_sec": 0.8},
            {"matched": True, "bad_drift": False, "subtitle_start_sec": 1.0, "subtitle_end_sec": 1.8},
            {"matched": False, "subtitle_start_sec": 20.0, "subtitle_end_sec": 20.8},
            {"matched": False, "subtitle_start_sec": 20.9, "subtitle_end_sec": 21.7},
            {"matched": True, "bad_drift": True, "subtitle_start_sec": 21.8, "subtitle_end_sec": 22.6, "start_drift_sec": 2.8},
            {"matched": True, "bad_drift": True, "subtitle_start_sec": 22.7, "subtitle_end_sec": 23.5, "start_drift_sec": 2.4},
        ]
    }

    cleaned, summary = _drop_clustered_unmatched_render_subtitles(subtitle_items, audit)

    assert summary["dropped_indexes"] == [2, 3]
    assert [item["text_final"] for item in cleaned] == ["字幕0", "字幕1", "字幕4", "字幕5"]


def test_drop_tail_compressed_duplicate_render_subtitles_removes_short_repeated_tail_rows() -> None:
    subtitle_items = [
        {"start_time": 581.92, "end_time": 591.36, "text_final": "同时它的肩带是做了一定的加宽也是起到了一定的减轻肩膀压力"},
        {"start_time": 591.36, "end_time": 597.12, "text_final": "力的效果吧这款单肩包说实话"},
        {"start_time": 597.12, "end_time": 600.496, "text_final": "你只有亲自到手去上身"},
        {"start_time": 600.496, "end_time": 604.256, "text_final": "真正的背一次就是在你日常场景啊"},
        {"start_time": 604.336, "end_time": 605.296, "text_final": "真正的使用一次"},
        {"start_time": 605.296, "end_time": 608.976, "text_final": "你能理解到它到底有多么的实用和优秀"},
        {
            "start_time": 609.696,
            "end_time": 610.446,
            "text_final": "力啊同时它的肩带是做了一定的加宽啊嗯也是起到了一定的这种减轻肩膀压力的效果",
        },
        {
            "start_time": 610.446,
            "end_time": 610.931,
            "text_final": "吧嗯这款单肩包说实话你只有亲自到手去上身呃实真正的背一次就是在你",
        },
        {
            "start_time": 610.971,
            "end_time": 611.495,
            "text_final": "日常场景啊真正的使用一次你才能理解到它到底有多么的实用和优秀嗯虽然它不如",
        },
        {"start_time": 611.535, "end_time": 616.975, "text_final": "我们这些机能包啊那么花里胡哨"},
    ]
    audit = {
        "events": [
            {
                "matched": True,
                "subtitle_start_sec": item["start_time"],
                "subtitle_end_sec": item["end_time"],
            }
            for item in subtitle_items
        ]
    }

    cleaned, summary = _drop_tail_compressed_duplicate_render_subtitles(subtitle_items, audit)

    assert summary["dropped_tail_duplicate_indexes"] == [6, 7, 8]
    assert [item["text_final"] for item in cleaned] == [
        "同时它的肩带是做了一定的加宽也是起到了一定的减轻肩膀压力",
        "力的效果吧这款单肩包说实话",
        "你只有亲自到手去上身",
        "真正的背一次就是在你日常场景啊",
        "真正的使用一次",
        "你能理解到它到底有多么的实用和优秀",
        "我们这些机能包啊那么花里胡哨",
    ]


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_reuses_local_section_profile_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_contexts: list[dict[str, Any]] = []

    def _capture_rewrite(
        subtitle_items: list[dict[str, Any]],
        *,
        render_plan: dict[str, Any] | None,
        section_profile_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        assert render_plan is None
        assert isinstance(section_profile_context, dict)
        captured_contexts.append(section_profile_context)
        return [dict(item) for item in subtitle_items]

    def _capture_resegment(
        subtitle_items: list[dict[str, Any]],
        *,
        render_plan: dict[str, Any] | None,
        section_profile_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        assert render_plan is None
        assert isinstance(section_profile_context, dict)
        captured_contexts.append(section_profile_context)
        return [dict(item) for item in subtitle_items]

    monkeypatch.setattr(
        pipeline_steps_module,
        "_rewrite_packaged_subtitle_copy",
        _capture_rewrite,
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_resegment_packaged_subtitles",
        _capture_resegment,
    )

    subtitles = await _map_subtitles_to_packaged_timeline(
        [{"start_time": 0.0, "end_time": 1.0, "text_final": "第一句"}],
        None,
        timeline_mapping={
            "transition_offsets": [],
            "intro_duration_sec": 0.0,
            "insert_plan": None,
            "insert_after_sec": 0.0,
            "effective_insert_duration_sec": 0.0,
        },
    )

    assert [item["text_final"] for item in subtitles] == ["第一句"]
    assert len(captured_contexts) == 2
    assert captured_contexts[0] is captured_contexts[1]


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_reuses_section_profile_context_from_timeline_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "resolve_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse section profile context from timeline mapping")),
    )

    subtitles = await _map_subtitles_to_packaged_timeline(
        [{"start_time": 0.0, "end_time": 1.0, "text_final": "第一句"}],
        {},
        timeline_mapping={
            "transition_offsets": [],
            "intro_duration_sec": 0.0,
            "insert_plan": None,
            "insert_after_sec": 0.0,
            "effective_insert_duration_sec": 0.0,
            "section_profile_context": {"subtitles": {}, "timeline_analysis": {}},
        },
    )

    assert [item["text_final"] for item in subtitles] == ["第一句"]


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_reuses_shared_section_profile_context_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, Any]] = []

    monkeypatch.setattr(
        pipeline_steps_module,
        "resolve_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should resolve section profile context via shared helper")),
    )

    def _capture_section_profile_context(render_plan: dict[str, Any] | None) -> dict[str, Any]:
        captured_payloads.append(dict(render_plan or {}))
        return {"subtitles": {}, "timeline_analysis": {}}

    monkeypatch.setattr(
        pipeline_steps_module,
        "_packaged_subtitle_section_profile_context",
        _capture_section_profile_context,
    )

    subtitles = await _map_subtitles_to_packaged_timeline(
        [{"start_time": 0.0, "end_time": 1.0, "text_final": "第一句"}],
        {"packaging_timeline": {"subtitles": {"style": "clean_white"}}},
        timeline_mapping={
            "transition_offsets": [],
            "intro_duration_sec": 0.0,
            "insert_plan": None,
            "insert_after_sec": 0.0,
            "effective_insert_duration_sec": 0.0,
        },
    )

    assert [item["text_final"] for item in subtitles] == ["第一句"]
    assert captured_payloads == [{"packaging_timeline": {"subtitles": {"style": "clean_white"}}}]


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_repairs_overlap_after_resegment() -> None:
    subtitles = await _map_subtitles_to_packaged_timeline(
        [
            {"start_time": 0.0, "end_time": 3.74, "text_final": "这是啊 先给大家变个魔术啊"},
            {"start_time": 3.64, "end_time": 5.18, "text_final": "大家看看这是什么东西啊"},
        ],
        None,
        timeline_mapping={
            "transition_offsets": [],
            "intro_duration_sec": 8.097,
            "insert_plan": None,
            "insert_after_sec": 0.0,
            "effective_insert_duration_sec": 0.0,
            "section_profile_context": {"subtitles": {}, "timeline_analysis": {}},
        },
    )

    assert subtitles[1]["start_time"] >= subtitles[0]["end_time"]
    assert subtitles[0]["packaged_subtitle_timing_repair"] == "trim_overlap_end"


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_merges_orphan_single_character_rows() -> None:
    subtitles = await _map_subtitles_to_packaged_timeline(
        [
            {"start_time": 240.313, "end_time": 242.247, "text_final": "当然"},
            {"start_time": 242.247, "end_time": 243.657, "text_final": "你"},
            {"start_time": 243.657, "end_time": 245.997, "text_final": "拉开以后你不去固定啊"},
        ],
        None,
        timeline_mapping={
            "transition_offsets": [],
            "intro_duration_sec": 0.0,
            "insert_plan": None,
            "insert_after_sec": 0.0,
            "effective_insert_duration_sec": 0.0,
            "section_profile_context": {"subtitles": {}, "timeline_analysis": {}},
        },
    )

    texts = [item["text_final"] for item in subtitles]
    assert "你" not in texts
    assert "你拉开以后你不去固定啊" in texts


def test_runtime_packaging_context_reads_nested_packaging_timeline_payload() -> None:
    context = _runtime_packaging_context(
        {
            "packaging_timeline": {
                "packaging": {
                    "intro": {"path": "intro.mp4"},
                    "music": {"path": "music.mp3", "enter_sec": 4.2, "timing_summary": {"review_recommended": False}},
                },
                "focus": {"focus_events": [{"event_type": "hook_focus", "start_time": 0.0, "end_time": 2.0, "text": "先讲结论"}]},
                "editing_accents": {
                    "style": "smart_effect_punch",
                    "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
                },
            }
        }
    )
    assert context["packaging_timeline"].pop("hyperframes")["schema"] == "roughcut.hyperframes.plan.v1"
    assert context == {
        "packaging_timeline": {
            "timeline_analysis": {},
            "editing_skill": {},
            "section_choreography": {},
            "subtitles": {},
            "packaging": {
                "intro": {"path": "intro.mp4"},
                "outro": None,
                "insert": None,
                "watermark": None,
                "music": {
                    "path": "music.mp3",
                    "enter_sec": 4.2,
                    "timing_summary": {"review_recommended": False},
                    "audio_cues": [
                        {
                            "kind": "bgm_entry",
                            "time_sec": 4.2,
                            "reason": "",
                            "review_recommended": False,
                        }
                    ],
                },
            },
            "editing_accents": {
                "style": "smart_effect_punch",
                "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
            },
            "focus": {
                "focus_events": [{"event_type": "hook_focus", "start_time": 0.0, "end_time": 2.0, "text": "先讲结论"}]
            },
        },
        "assets": {
            "intro": {"path": "intro.mp4"},
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": {
                "path": "music.mp3",
                "enter_sec": 4.2,
                "timing_summary": {"review_recommended": False},
                "audio_cues": [
                    {
                        "kind": "bgm_entry",
                        "time_sec": 4.2,
                        "reason": "",
                        "review_recommended": False,
                    }
                ],
            },
        },
        "editing_accents": {
            "style": "smart_effect_punch",
            "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
        },
        "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
        "section_choreography": {},
        "subtitles": {},
        "focus": {
            "focus_events": [{"event_type": "hook_focus", "start_time": 0.0, "end_time": 2.0, "text": "先讲结论"}]
        },
        "audio_cues": [
            {
                "kind": "bgm_entry",
                "time_sec": 4.2,
                "reason": "",
                "review_recommended": False,
            }
        ],
        "section_profile_context": {
            "subtitles": {},
            "timeline_analysis": {},
        },
        "has_packaging": True,
        "has_packaging_assets": True,
        "has_editing_accents": True,
    }


def test_runtime_packaging_context_reuses_local_normalized_packaging_payload() -> None:
    assert not hasattr(pipeline_steps_module, "packaging_timeline_assets")
    assert not hasattr(pipeline_steps_module, "packaging_timeline_editing_accents")
    assert not hasattr(pipeline_steps_module, "packaging_timeline_has_packaging_assets")
    assert not hasattr(pipeline_steps_module, "packaging_timeline_has_editing_accents")

    runtime_context = _runtime_packaging_context(
        {
            "packaging": {
                "outro": {"path": "outro.mp4"},
            },
            "editing_accents": {
                "transitions": {"enabled": False, "boundary_indexes": [], "duration_sec": 0.12},
                "emphasis_overlays": [{"start_time": 0.5, "end_time": 1.0, "text": "demo"}],
            },
        }
    )
    packaging_timeline = dict(runtime_context["packaging_timeline"])
    assert packaging_timeline.pop("hyperframes")["schema"] == "roughcut.hyperframes.plan.v1"
    assert {**runtime_context, "packaging_timeline": packaging_timeline} == {
        "packaging_timeline": {
            "timeline_analysis": {},
            "editing_skill": {},
            "section_choreography": {},
            "subtitles": {},
            "packaging": {
                "intro": None,
                "outro": {"path": "outro.mp4"},
                "insert": None,
                "watermark": None,
                "music": None,
            },
            "editing_accents": {
                "transitions": {"enabled": False, "boundary_indexes": [], "duration_sec": 0.12},
                "emphasis_overlays": [{"start_time": 0.5, "end_time": 1.0, "text": "demo"}],
            },
        },
        "assets": {
            "intro": None,
            "outro": {"path": "outro.mp4"},
            "insert": None,
            "watermark": None,
            "music": None,
        },
        "editing_accents": {
            "transitions": {"enabled": False, "boundary_indexes": [], "duration_sec": 0.12},
            "emphasis_overlays": [{"start_time": 0.5, "end_time": 1.0, "text": "demo"}],
        },
        "transitions": {"enabled": False, "boundary_indexes": [], "duration_sec": 0.12},
        "section_choreography": {},
        "subtitles": {},
        "focus": None,
        "audio_cues": [],
        "section_profile_context": {
            "subtitles": {},
            "timeline_analysis": {},
        },
        "has_packaging": True,
        "has_packaging_assets": True,
        "has_editing_accents": True,
    }


def test_runtime_packaging_context_reuses_local_packaging_timeline_for_section_profile_context_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_packaging_timelines: list[dict[str, Any]] = []

    def _capture_section_profile_context(
        _render_plan: dict[str, Any] | None,
        *,
        packaging_timeline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert isinstance(packaging_timeline, dict)
        captured_packaging_timelines.append(dict(packaging_timeline))
        return {
            "subtitles": {"style": "clean_white"},
            "timeline_analysis": {"hook_end_sec": 1.5},
        }

    monkeypatch.setattr(
        pipeline_steps_module,
        "_packaged_subtitle_section_profile_context",
        _capture_section_profile_context,
    )

    runtime_context = _runtime_packaging_context(
        {
            "packaging": {
                "outro": {"path": "outro.mp4"},
            },
            "subtitles": {"style": "clean_white"},
            "timeline_analysis": {"hook_end_sec": 1.5},
            "editing_accents": {
                "transitions": {"enabled": False, "boundary_indexes": [], "duration_sec": 0.12},
            },
        }
    )

    assert runtime_context["section_profile_context"] == {
        "subtitles": {"style": "clean_white"},
        "timeline_analysis": {"hook_end_sec": 1.5},
    }
    assert captured_packaging_timelines == [runtime_context["packaging_timeline"]]


def test_runtime_render_plan_context_reads_render_plan_once() -> None:
    assert _runtime_render_plan_context(
        {
            "automatic_gate": {"blocking": True},
            "manual_editor": {
                "change_scope": "subtitle_only",
                "video_transform": {"rotation_manual": True, "rotation_cw": 90},
            },
            "delivery": {"frame_rate_mode": "specified", "frame_rate_preset": "50"},
            "voice_processing": {"noise_reduction": False},
            "loudness": {"target_lufs": -14.0, "peak_limit": -1.0},
            "avatar_commentary": {"mode": "segmented_audio_passthrough"},
        }
    ) == {
        "automatic_gate": {"blocking": True},
        "manual_editor": {
            "change_scope": "subtitle_only",
            "video_transform": {"rotation_manual": True, "rotation_cw": 90},
        },
        "delivery": {"frame_rate_mode": "specified", "frame_rate_preset": "50"},
        "video_transform": {
            "rotation_manual": True,
            "rotation_cw": 90,
            "aspect_ratio": "source",
            "resolution_mode": "source",
            "resolution_preset": "1080p",
        },
        "avatar_plan": {"mode": "segmented_audio_passthrough"},
        "voice_processing": {"noise_reduction": False},
        "loudness": {"target_lufs": -14.0, "peak_limit": -1.0},
    }


def test_runtime_render_plan_context_includes_strategy_review_context_when_present() -> None:
    runtime_context = _runtime_render_plan_context(
        {
            "strategy_review_context": {
                "strategy_review_gates": {
                    "pipeline_plan": {
                        "strategy_type": "narrative_assembly",
                        "review_gates": ["timeline_preview_required"],
                    }
                }
            }
        }
    )

    assert runtime_context["strategy_review_context"]["strategy_review_gates"]["pipeline_plan"][
        "strategy_type"
    ] == "narrative_assembly"


@pytest.mark.asyncio
async def test_persist_render_runtime_diagnostics_stores_strategy_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.added: list[Any] = []
            self.committed = False

        def add(self, artifact: Any) -> None:
            self.added.append(artifact)

        async def commit(self) -> None:
            self.committed = True

    async def fake_load_latest_optional_artifact(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None

    monkeypatch.setattr(
        pipeline_steps_module,
        "_load_latest_optional_artifact",
        fake_load_latest_optional_artifact,
    )
    session = FakeSession()

    await _persist_render_runtime_diagnostics(
        session,
        job_id=uuid4(),
        step_id=None,
        strategy_render_validation={
            "schema": "strategy_render_validation.v1",
            "status": "blocking",
            "blocking": True,
            "reason": "strategy_timeline_preview_missing",
        },
    )

    assert session.committed is True
    assert len(session.added) == 1
    assert session.added[0].data_json["strategy_render_validation"]["reason"] == (
        "strategy_timeline_preview_missing"
    )


def test_resolve_transition_overlap_offsets_reuses_local_normalized_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "resolve_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse shared packaging_timeline_transitions helper")),
    )

    assert _resolve_transition_overlap_offsets(
        {
            "editing_accents": {
                "transitions": {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
            }
        },
        keep_segments=[
            {"start": 0.0, "end": 3.0},
            {"start": 4.0, "end": 7.0},
        ],
    ) == [(3.0, 0.12)]


def test_resolve_transition_overlap_offsets_reuses_shared_transition_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_transitions",
        lambda _payload: {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
    )

    assert _resolve_transition_overlap_offsets(
        {"editing_accents": {"transitions": {"enabled": False}}},
        keep_segments=[
            {"start": 0.0, "end": 3.0},
            {"start": 4.0, "end": 7.0},
        ],
    ) == [(3.0, 0.12)]


def test_resolve_transition_overlap_offsets_reuses_passed_transitions() -> None:
    assert _resolve_transition_overlap_offsets(
        None,
        keep_segments=[
            {"start": 0.0, "end": 3.0},
            {"start": 4.0, "end": 7.0},
        ],
        transitions={"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
    ) == [(3.0, 0.12)]


def test_pipeline_steps_exports_packaging_timeline_resolver_for_render_runtime() -> None:
    assert callable(pipeline_steps_module.resolve_packaging_timeline_payload)


def test_shared_editorial_keep_segments_resolve_prefers_matching_refine_plan() -> None:
    assert resolve_editorial_keep_segments(
        editorial_timeline_payload={"segments": [{"type": "keep", "start": 0.0, "end": 10.0}]},
        refine_plan_payload={
            "editorial_timeline_id": "timeline-1",
            "editorial_timeline_version": 3,
            "keep_segments": [{"start": 2.0, "end": 6.0}],
        },
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=3,
        prefer_refine_plan=True,
        upper_bound=10.0,
        merge_gap_sec=0.05,
        minimum_duration_sec=0.05,
    ) == [{"start": 2.0, "end": 6.0}]


def test_resolve_editorial_keep_segments_reuses_local_editorial_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import editorial_timeline as editorial_timeline_module

    monkeypatch.setattr(
        editorial_timeline_module,
        "editorial_keep_segments",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local editorial segments")),
    )

    assert resolve_editorial_keep_segments(
        editorial_timeline_payload={
            "segments": [
                {"type": "keep", "start": 1.0, "end": 3.0},
                {"type": "cut", "start": 3.0, "end": 5.0},
                {"type": "keep", "start": 5.0, "end": 6.5},
            ]
        },
        prefer_refine_plan=False,
        upper_bound=8.0,
        merge_gap_sec=0.0,
        minimum_duration_sec=0.0,
    ) == [
        {"start": 1.0, "end": 3.0},
        {"start": 5.0, "end": 6.5},
    ]


def test_resolve_refine_keep_segments_for_timeline_reuses_local_fallback_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import editorial_timeline as editorial_timeline_module

    monkeypatch.setattr(
        editorial_timeline_module,
        "editorial_keep_segments",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local fallback segments")),
    )

    assert resolve_refine_keep_segments_for_timeline(
        None,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=3,
        fallback_segments=[
            {"type": "keep", "start": 1.0, "end": 3.0},
            {"type": "cut", "start": 3.0, "end": 5.0},
            {"type": "keep", "start": 5.0, "end": 6.5},
        ],
    ) == [
        {"start": 1.0, "end": 3.0},
        {"start": 5.0, "end": 6.5},
    ]


def test_shared_editorial_segments_builder_supports_reason_overrides() -> None:
    assert build_shared_editorial_segments_from_keep_segments(
        [{"start": 1.0, "end": 3.0}],
        source_duration_sec=4.0,
        keep_reason="editorial_keep",
        cut_reason="editorial_cut",
    ) == [
        {"start": 0.0, "end": 1.0, "type": "cut", "reason": "editorial_cut"},
        {"start": 1.0, "end": 3.0, "type": "keep", "reason": "editorial_keep"},
        {"start": 3.0, "end": 4.0, "type": "cut", "reason": "editorial_cut"},
    ]


def test_shared_editorial_timeline_helpers_return_safe_copies() -> None:
    payload = {
        "segments": [{"type": "keep", "start": 1.0, "end": 3.0}],
        "analysis": {"accepted_cuts": [{"start": 0.0, "end": 1.0, "reason": "silence"}]},
    }

    segments = editorial_timeline_segments(payload)
    analysis = editorial_timeline_analysis(payload)
    segments[0]["start"] = 9.0
    analysis["accepted_cuts"][0]["reason"] = "mutated"

    assert payload["segments"][0]["start"] == 1.0
    assert payload["analysis"]["accepted_cuts"][0]["reason"] == "silence"


def test_shared_editorial_cut_segments_accept_current_and_legacy_types() -> None:
    payload = {
        "segments": [
            {"type": "keep", "start": 0.0, "end": 1.0},
            {"type": "cut", "start": 1.0, "end": 2.0, "reason": "silence"},
            {"type": "remove", "start": 2.0, "end": 3.5, "reason": "legacy_remove"},
        ]
    }

    cut_segments = editorial_cut_segments(payload)
    cut_segments[0]["reason"] = "mutated"

    assert editorial_cut_segments(payload) == [
        {"type": "cut", "start": 1.0, "end": 2.0, "reason": "silence"},
        {"type": "remove", "start": 2.0, "end": 3.5, "reason": "legacy_remove"},
    ]


def test_shared_editorial_cut_segments_reuse_local_segments_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import editorial_timeline as editorial_timeline_module

    monkeypatch.setattr(
        editorial_timeline_module,
        "editorial_timeline_segments",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local segments payload")),
    )

    assert editorial_cut_segments(
        {
            "segments": [
                {"type": "keep", "start": 0.0, "end": 1.0},
                {"type": "cut", "start": 1.0, "end": 2.0, "reason": "silence"},
            ]
        }
    ) == [
        {"type": "cut", "start": 1.0, "end": 2.0, "reason": "silence"},
    ]


def test_shared_editorial_subtitle_projection_returns_safe_copy() -> None:
    payload = {
        "subtitle_projection": {
            "items": [{"index": 0, "start_time": 1.0, "end_time": 2.0, "text_final": "demo"}],
            "overrides": [{"index": 0, "text_final": "override"}],
        }
    }

    projection = editorial_timeline_subtitle_projection(payload)
    assert projection is not None
    projection["items"][0]["text_final"] = "mutated"

    assert editorial_timeline_subtitle_projection(payload) == {
        "items": [{"index": 0, "start_time": 1.0, "end_time": 2.0, "text_final": "demo"}],
        "overrides": [{"index": 0, "text_final": "override"}],
    }
    assert editorial_timeline_subtitle_projection({}) is None


def test_activity_decisions_edit_plan_summary_counts_cut_and_remove_segments() -> None:
    editorial_timeline = SimpleNamespace(
        timeline_type="editorial",
        data_json={
            "segments": [
                {"type": "keep", "start": 0.0, "end": 1.0},
                {"type": "cut", "start": 1.0, "end": 2.0, "reason": "silence"},
                {"type": "remove", "start": 3.0, "end": 4.5, "reason": "legacy_remove"},
            ]
        },
        created_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
    )

    decisions = _build_activity_decisions([], [editorial_timeline], [], None)
    edit_plan = next(item for item in decisions if item["kind"] == "edit_plan")

    assert edit_plan["summary"] == "建议移除 2 段，共 2.5 秒"
    assert edit_plan["detail"] == "legacy_remove 1 段；silence 1 段"


def test_render_plan_helpers_return_defaults_and_safe_copies() -> None:
    payload = {
        "workflow_preset": "knowledge_explainer",
        "automatic_gate": {"blocking": True},
        "manual_editor": {"video_transform": {"aspect_ratio": "9:16"}},
        "delivery": {"resolution_mode": "fixed", "resolution_preset": "720p"},
        "loudness": {"target_lufs": -14.0, "peak_limit": -1.0},
        "voice_processing": {"noise_reduction": False},
        "avatar_commentary": {"mode": "segmented_audio_passthrough"},
        "dialogue_polish": {"enabled": True},
    }

    gate = render_plan_automatic_gate(payload)
    manual_editor = render_plan_manual_editor(payload)
    delivery = render_plan_delivery(payload)
    loudness = render_plan_loudness(payload)
    voice_processing = render_plan_voice_processing(payload)
    avatar = render_plan_avatar_commentary(payload)
    dialogue_polish = render_plan_dialogue_polish(payload)

    gate["blocking"] = False
    manual_editor["video_transform"]["aspect_ratio"] = "1:1"
    delivery["resolution_preset"] = "1080p"
    loudness["target_lufs"] = -20.0
    voice_processing["noise_reduction"] = True
    avatar["mode"] = "mutated"
    dialogue_polish["enabled"] = False

    assert render_plan_workflow_preset(payload) == "knowledge_explainer"
    assert render_plan_workflow_preset({}, default="fallback") == "fallback"
    assert payload["automatic_gate"]["blocking"] is True
    assert payload["manual_editor"]["video_transform"]["aspect_ratio"] == "9:16"
    assert payload["delivery"]["resolution_preset"] == "720p"
    assert payload["loudness"]["target_lufs"] == -14.0
    assert payload["voice_processing"]["noise_reduction"] is False
    assert payload["avatar_commentary"]["mode"] == "segmented_audio_passthrough"
    assert payload["dialogue_polish"]["enabled"] is True


def test_render_plan_video_transform_merges_manual_editor_and_delivery_defaults() -> None:
    payload = {
        "manual_editor": {"video_transform": {"rotation_manual": True, "rotation_cw": 90, "aspect_ratio": "9:16"}},
        "delivery": {"aspect_ratio": "1:1", "resolution_mode": "fixed", "resolution_preset": "720p"},
    }

    video_transform = render_plan_video_transform(payload)
    video_transform["resolution_preset"] = "1080p"

    assert render_plan_video_transform(payload) == {
        "rotation_manual": True,
        "rotation_cw": 90,
        "aspect_ratio": "9:16",
        "resolution_mode": "fixed",
        "resolution_preset": "720p",
    }


def test_render_plan_video_transform_reuses_local_render_plan_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        render_plan_module,
        "render_plan_manual_editor",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local manual_editor payload")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "render_plan_delivery",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local delivery payload")),
    )

    assert render_plan_video_transform(
        {
            "manual_editor": {"video_transform": {"rotation_manual": True, "rotation_cw": 90}},
            "delivery": {"aspect_ratio": "1:1", "resolution_mode": "fixed", "resolution_preset": "720p"},
        }
    ) == {
        "rotation_manual": True,
        "rotation_cw": 90,
        "aspect_ratio": "1:1",
        "resolution_mode": "fixed",
        "resolution_preset": "720p",
    }


def test_manual_editor_render_plan_context_reads_render_plan_once() -> None:
    context = _manual_editor_render_plan_context(
        {
            "workflow_preset": "knowledge_explainer",
            "packaging_timeline": {
                "editing_skill": {"key": "knowledge_explainer"},
                "subtitles": {"version": 3},
            },
            "manual_editor": {"video_transform": {"rotation_manual": True, "rotation_cw": 90}},
            "loudness": {"target_lufs": -18.0},
            "voice_processing": {"noise_reduction": True},
            "dialogue_polish": {"enabled": True},
            "avatar_commentary": {"mode": "segmented_audio_passthrough"},
            "strategy_review_context": {
                "strategy_review_gates": {
                    "review_gate_status": {"blocking": False},
                },
                "strategy_timeline_preview": {
                    "segments": [{"segment_id": "preview_1"}],
                },
            },
        }
    )

    packaging_timeline = dict(context["packaging_timeline"])
    assert packaging_timeline.pop("hyperframes", None) is not None
    assert packaging_timeline == {
        "timeline_analysis": {},
        "editing_skill": {"key": "knowledge_explainer"},
        "section_choreography": {},
        "subtitles": {"version": 3},
        "packaging": {
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        "editing_accents": {},
    }
    assert context["workflow_preset"] == "knowledge_explainer"
    assert context["delivery"] == {}
    assert context["video_transform"] == {
        "rotation_manual": True,
        "rotation_cw": 90,
        "aspect_ratio": "source",
        "resolution_mode": "source",
        "resolution_preset": "1080p",
    }
    assert context["loudness"] == {"target_lufs": -18.0}
    assert context["voice_processing"] == {"noise_reduction": True}
    assert context["dialogue_polish_plan"] == {"enabled": True}
    assert context["avatar_commentary_plan"] == {"mode": "segmented_audio_passthrough"}
    assert context["strategy_review_context"] == {
        "strategy_review_gates": {
            "review_gate_status": {"blocking": False},
        },
        "strategy_timeline_preview": {
            "segments": [{"segment_id": "preview_1"}],
        },
    }


def test_manual_video_transform_from_render_plan_reuses_caller_render_plan_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_render_plan_context",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse caller render plan context")),
    )

    assert _manual_video_transform_from_render_plan(
        None,
        render_plan_context={
            "video_transform": {
                "rotation_manual": True,
                "rotation_cw": 90,
                "aspect_ratio": "9:16",
                "resolution_mode": "specified",
                "resolution_preset": "1440p",
            }
        },
    ) == {
        "rotation_manual": True,
        "rotation_cw": 90,
        "aspect_ratio": "9:16",
        "resolution_mode": "specified",
        "resolution_preset": "1440p",
    }


def test_manual_video_transform_from_render_plan_reuses_caller_video_transform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_render_plan_context",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse caller video_transform")),
    )

    assert _manual_video_transform_from_render_plan(
        None,
        video_transform={
            "rotation_manual": True,
            "rotation_cw": 90,
            "aspect_ratio": "9:16",
            "resolution_mode": "specified",
            "resolution_preset": "1440p",
        },
    ) == {
        "rotation_manual": True,
        "rotation_cw": 90,
        "aspect_ratio": "9:16",
        "resolution_mode": "specified",
        "resolution_preset": "1440p",
    }


def test_manual_segments_build_otio_style_tracks() -> None:
    segments = _build_editorial_segments_from_keep_segments(
        [
            {"start": 1.0, "end": 3.0},
            {"start": 5.0, "end": 6.5},
        ],
        source_duration_sec=8.0,
    )

    payload = _build_otio_style_manual_tracks(
        segments,
        source_url="source.mp4",
        source_duration_sec=8.0,
    )

    assert payload["schema"] == "roughcut.editorial.v2"
    assert payload["source_duration_sec"] == 8.0
    assert payload["output_duration_sec"] == 3.5
    source_track, output_track = payload["tracks"]
    assert source_track["name"] == "source_video"
    assert [item["type"] for item in source_track["items"]] == ["gap", "clip", "gap", "clip", "gap"]
    assert output_track["name"] == "output_video"
    assert [item["source_range"] for item in output_track["items"]] == [
        {"start": 1.0, "duration": 2.0},
        {"start": 5.0, "duration": 1.5},
    ]
    assert [item["output_range"] for item in output_track["items"]] == [
        {"start": 0.0, "duration": 2.0},
        {"start": 2.0, "duration": 1.5},
    ]


def test_otio_export_reads_output_track_when_present() -> None:
    segments = _build_editorial_segments_from_keep_segments(
        [
            {"start": 1.0, "end": 3.0},
            {"start": 5.0, "end": 6.5},
        ],
        source_duration_sec=8.0,
    )
    tracks_payload = _build_otio_style_manual_tracks(
        segments,
        source_url="source.mp4",
        source_duration_sec=8.0,
    )

    otio_json = export_to_otio(
        {
            "source": "source.mp4",
            "segments": segments,
            "tracks": tracks_payload["tracks"],
        }
    )

    assert '"keep 2"' in otio_json
    assert '"keep 4"' in otio_json
    assert '"gap 1"' not in otio_json


def test_manual_subtitle_overrides_apply_text_and_timing_with_gap() -> None:
    subtitles = [
        {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "old one"},
        {"index": 1, "start_time": 1.1, "end_time": 2.0, "text_final": "old two"},
    ]

    adjusted = _apply_manual_subtitle_overrides(
        subtitles,
        [
            {"index": 0, "start_time": 0.2, "end_time": 1.5, "text_final": "new one"},
            {"index": 1, "start_time": 1.4, "end_time": 1.8},
        ],
        output_duration_sec=2.0,
    )

    assert adjusted[0]["text_final"] == "new one"
    assert adjusted[0]["start_time"] == 0.2
    assert adjusted[0]["end_time"] == 1.5
    assert adjusted[1]["start_time"] == 1.52
    assert adjusted[1]["end_time"] == 1.8


def test_manual_subtitle_overrides_can_insert_and_delete_items() -> None:
    subtitles = [
        {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "first"},
        {"index": 1, "start_time": 1.1, "end_time": 2.0, "text_final": "second"},
    ]

    adjusted = _apply_manual_subtitle_overrides(
        subtitles,
        [
            {"index": 1, "delete": True},
            {"index": 9, "start_time": 1.2, "end_time": 1.8, "text_final": "inserted"},
        ],
        output_duration_sec=2.0,
    )

    assert [item["index"] for item in adjusted] == [0, 9]
    assert adjusted[1]["text_final"] == "inserted"
    assert adjusted[1]["start_time"] == 1.2
    assert adjusted[1]["end_time"] == 1.8


def test_manual_editor_subtitle_payload_preserves_editable_canonical_body() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "好，今天给大家介绍，嗯，狐蝠工业。",
            "text_norm": "好，今天给大家介绍，嗯，狐蝠工业。",
            "text_final": "好，今天给大家介绍，嗯，狐蝠工业。",
        },
        index=0,
    )

    assert payload.text_final == "好，今天给大家介绍，嗯，狐蝠工业。"


def test_manual_editor_rule_segments_expose_typed_full_transcript_candidates() -> None:
    segments = _manual_editor_rule_segments(
        {
            "accepted_cuts": [
                {
                    "start": 1.0,
                    "end": 1.9,
                    "reason": "silence",
                },
                {
                    "start": 4.0,
                    "end": 5.4,
                    "reason": "restart_retake",
                    "llm_review": {
                        "verdict": "cut",
                        "confidence": 0.88,
                        "reason": "前一句明确重录，后一句更完整。",
                    },
                },
            ],
            "manual_editor_rule_candidates": [
                {
                    "start": 2.0,
                    "end": 2.18,
                    "reason": "filler_word",
                    "score": 0.91,
                    "candidate_stage": "manual_editor_full_transcript",
                    "auto_applied": False,
                },
                {
                    "start": 3.0,
                    "end": 3.42,
                    "reason": "repeated_speech",
                    "score": 0.76,
                    "candidate_stage": "manual_editor_full_transcript",
                    "auto_applied": False,
                },
            ],
        }
    )

    assert [(item.kind, item.start, item.end) for item in segments] == [
        ("pause", 1.0, 1.9),
        ("filler", 2.0, 2.18),
        ("repeated", 3.0, 3.42),
        ("smart_delete", 4.0, 5.4),
    ]
    assert segments[1].source == "manual_editor_rule_candidate"
    assert segments[1].confidence == 0.91
    assert segments[1].auto_applied is False
    assert segments[2].reason == "repeated_speech"
    assert segments[3].source == "llm_cut_review"
    assert segments[3].detail == "前一句明确重录，后一句更完整。"
    assert segments[1].stage == "manual_editor_full_transcript"
    assert segments[3].stage == "accepted_cut"


def test_manual_editor_rule_segments_expose_provenance_fields() -> None:
    segments = _manual_editor_rule_segments(
        {
            "accepted_cuts": [
                {
                    "start": 1.0,
                    "end": 1.2,
                    "reason": "silence",
                    "risk_level": "high",
                    "rule_id": "accepted-cut-1",
                },
            ],
            "manual_editor_rule_candidates": [
                {
                    "start": 2.0,
                    "end": 2.35,
                    "reason": "filler_word",
                    "candidate_stage": "manual_editor_smart_cut_rules",
                    "candidate_id": "filler-1",
                    "score": 0.92,
                    "source_text": "嗯",
                    "filler_mode": "standalone",
                    "match_surface": "standalone",
                    "risk_level": "low",
                },
                {
                    "start": 3.0,
                    "end": 3.48,
                    "reason": "repeated_speech",
                    "candidate_stage": "manual_editor_full_transcript",
                    "risk_level": "medium",
                    "rule_id": "repeated-1",
                    "source_text": "这个啊",
                    "auto_applied": True,
                },
            ],
        }
    )

    assert [(item.kind, item.start, item.end) for item in segments] == [
        ("pause", 1.0, 1.2),
        ("filler", 2.0, 2.35),
        ("repeated", 3.0, 3.48),
    ]
    assert segments[0].stage == "accepted_cut"
    assert segments[0].risk_level == "high"
    assert segments[0].rule_id == "accepted-cut-1"
    assert segments[1].stage == "manual_editor_smart_cut_rules"
    assert segments[1].match_surface == "standalone"
    assert segments[1].rule_id == "filler-1"
    assert segments[1].risk_level == "low"
    assert segments[1].match_surface_layer == "raw"
    assert segments[2].stage == "manual_editor_full_transcript"
    assert segments[2].rule_id == "repeated-1"
    assert segments[2].risk_level == "medium"


def test_manual_editor_segments_accept_cut_analysis_artifact_payload() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {
                    "start": 1.0,
                    "end": 1.4,
                    "reason": "silence",
                }
            ],
            "manual_editor_rule_candidates": [
                {
                    "start": 2.0,
                    "end": 2.18,
                    "reason": "filler_word",
                    "score": 0.93,
                    "candidate_stage": "manual_editor_full_transcript",
                    "auto_applied": False,
                }
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    rule_segments = _manual_editor_rule_segments(payload)
    assert payload["schema"] == "cut_analysis.v1"
    assert [(item.kind, item.start, item.end) for item in rule_segments] == [
        ("pause", 1.0, 1.4),
        ("filler", 2.0, 2.18),
    ]


@pytest.mark.asyncio
async def test_load_manual_editor_cut_analysis_payload_prefers_artifact_and_reapplies_current_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            data_json={
                "schema": "cut_analysis.v1",
                "candidate_count": 1,
                "rule_candidates": [
                    {
                        "start": 0.0,
                        "end": 0.4,
                        "reason": "filler_word",
                        "candidate_stage": "manual_editor_smart_cut_rules",
                        "source_text": "嗯",
                        "filler_mode": "standalone",
                    }
                ],
            }
        )

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)

    payload = await _load_manual_editor_cut_analysis_payload(
        SimpleNamespace(),
        job=SimpleNamespace(id=uuid4(), source_name="demo.mp4", job_flow_mode="manual"),
        editorial_timeline_payload={"analysis": {"accepted_cuts": [{"start": 2.0, "end": 3.0, "reason": "silence"}]}},
        source_subtitles=[{"start_time": 0.0, "end_time": 0.4, "text_final": "嗯"}],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": True,
            "fillerContinuousEnabled": False,
            "catchphraseEnabled": False,
            "fillers": "嗯",
            "catchphrases": "",
        },
    )

    assert payload["schema"] == "cut_analysis.v1"
    assert payload["source_name"] == "demo.mp4"
    assert any(
        item.get("reason") == "filler_word"
        and item.get("source_text") == "嗯"
        and item.get("candidate_stage") == "manual_editor_smart_cut_rules"
        for item in (payload.get("rule_candidates") or [])
        if isinstance(item, dict)
    )


@pytest.mark.asyncio
async def test_load_manual_editor_cut_analysis_payload_passes_content_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(data_json={"schema": "cut_analysis.v1"})

    def _fake_build_cut_analysis_payload(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"schema": "cut_analysis.v1", "rule_candidates": []}

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(jobs_module, "build_cut_analysis_payload", _fake_build_cut_analysis_payload)

    content_profile = {"subject_model": "EDC17", "subject_type": "手电"}
    await _load_manual_editor_cut_analysis_payload(
        SimpleNamespace(),
        job=SimpleNamespace(id=uuid4(), source_name="demo.mp4", job_flow_mode="manual"),
        editorial_timeline_payload={"analysis": {"accepted_cuts": []}},
        source_subtitles=[{"start_time": 0.0, "end_time": 1.0, "text_final": "然后呢"}],
        smart_cut_rules={"smartDeleteEnabled": True},
        content_profile=content_profile,
    )

    assert captured["content_profile"] == content_profile


def test_manual_editor_editorial_context_reads_projection_analysis_and_keep_segments_once() -> None:
    context = _manual_editor_editorial_context(
        {
            "segments": [
                {"type": "keep", "start": 0.0, "end": 1.0},
                {"type": "keep", "start": 1.5, "end": 2.5},
            ],
            "subtitle_projection": {
                "mode": "ripple_keep_segments",
                "items": [{"start_time": 0.0, "end_time": 1.0, "text_final": "第一句"}],
            },
            "analysis": {
                "accepted_cuts": [{"start": 2.0, "end": 3.0, "reason": "silence"}],
            },
        }
    )

    assert context == {
        "subtitle_projection": {
            "mode": "ripple_keep_segments",
            "items": [{"start_time": 0.0, "end_time": 1.0, "text_final": "第一句"}],
        },
        "editorial_analysis": {
            "accepted_cuts": [{"start": 2.0, "end": 3.0, "reason": "silence"}],
        },
        "raw_keep_segments": [
            {"start": 0.0, "end": 1.0},
            {"start": 1.5, "end": 2.5},
        ],
    }


@pytest.mark.asyncio
async def test_load_manual_editor_cut_analysis_payload_reuses_passed_editorial_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> None:
        return None

    def _capture_manual_editor_cut_analysis_payload(
        artifact_payload: dict[str, Any] | None,
        editorial_analysis: dict[str, Any] | None,
        **kwargs: object,
    ) -> dict[str, object]:
        captured["artifact_payload"] = artifact_payload
        captured["editorial_analysis"] = editorial_analysis
        captured["kwargs"] = dict(kwargs)
        return {"schema": "cut_analysis.v1"}

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        jobs_module,
        "editorial_timeline_analysis",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse passed editorial analysis")),
    )
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_cut_analysis_payload",
        _capture_manual_editor_cut_analysis_payload,
    )

    await _load_manual_editor_cut_analysis_payload(
        SimpleNamespace(),
        job=SimpleNamespace(id=uuid4(), source_name="demo.mp4", job_flow_mode="manual"),
        editorial_timeline_payload={"analysis": {"accepted_cuts": []}},
        editorial_analysis={"accepted_cuts": [{"start": 2.0, "end": 3.0, "reason": "silence"}]},
        source_subtitles=[{"start_time": 0.0, "end_time": 1.0, "text_final": "然后呢"}],
        smart_cut_rules={"smartDeleteEnabled": True},
    )

    assert captured["artifact_payload"] is None
    assert captured["editorial_analysis"] == {
        "accepted_cuts": [{"start": 2.0, "end": 3.0, "reason": "silence"}],
    }


def test_manual_editor_build_refine_decision_plan_from_render_plan_reuses_shared_contract() -> None:
    payload = _manual_editor_build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 0.0, "end": 5.0}],
        source_duration_sec=12.0,
        subtitle_fingerprint="fp-1",
        render_plan_data={"loudness": {"integrated_lufs": -16.0}},
        render_plan_version=7,
        cut_analysis={"candidate_count": 3, "auto_apply_candidate_count": 1, "manual_confirm_candidate_count": 2},
        video_transform={"rotation_cw": 90},
        smart_cut_rules={"pauseEnabled": True, "pauseThresholdSec": 0.8},
        mode="manual_refine",
        note="manual-note",
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=4,
    )

    assert payload["schema"] == "refine_decision_plan.v1"
    assert payload["mode"] == "manual_refine"
    assert payload["keep_segments"] == [{"start": 0.0, "end": 5.0}]
    assert payload["render_plan_version"] == 7
    assert payload["smart_cut_rules"]["pauseEnabled"] is True
    assert payload["video_transform"]["rotation_cw"] == 90
    assert payload["candidate_summary"]["total"] == 3
    assert payload["candidate_summary"]["auto_apply"] == 1
    assert payload["candidate_summary"]["manual_confirm"] == 2
    assert payload["candidate_summary"]["risk_levels"] == {}


def test_manual_editor_build_refine_decision_plan_from_render_plan_reuses_passed_audio_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _build_refine_decision_plan_from_render_plan(**kwargs):
        captured.update(kwargs)
        return {"schema": "refine_decision_plan.v1"}

    monkeypatch.setattr(
        jobs_module,
        "build_refine_decision_plan_from_render_plan",
        _build_refine_decision_plan_from_render_plan,
    )

    payload = _manual_editor_build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 0.0, "end": 5.0}],
        source_duration_sec=12.0,
        subtitle_fingerprint="fp-1",
        render_plan_data={"loudness": {"target_lufs": -18.0}},
        render_plan_version=7,
        cut_analysis={},
        audio_defaults={"target_lufs": -16.0, "noise_reduction": True},
        video_transform={"rotation_cw": 90},
        smart_cut_rules={"pauseEnabled": True},
        mode="manual_refine",
    )

    assert payload == {"schema": "refine_decision_plan.v1"}
    assert captured["audio_defaults"] == {"target_lufs": -16.0, "noise_reduction": True}
    assert captured["render_plan_data"] is None


def test_cut_analysis_payload_adds_backend_smart_cut_rule_candidates() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "嗯我们开始"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "这个就是重点"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": True,
            "fillerSentenceTailEnabled": False,
            "catchphraseEnabled": True,
            "fillers": "嗯",
            "catchphrases": "就是",
        },
    )

    candidates = payload["rule_candidates"]
    assert any(item["reason"] == "filler_word" and item["source_text"] == "嗯" and item["filler_mode"] == "sentence_head" for item in candidates)
    assert any(item["reason"] == "catchphrase_phrase" and item["source_text"] == "就是" for item in candidates)


def test_cut_analysis_payload_tracks_candidate_risk_summary() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {"start": 1.0, "end": 1.3, "reason": "silence", "auto_applied": True},
                {"start": 2.0, "end": 2.8, "reason": "restart_retake", "auto_applied": False},
            ],
            "manual_editor_rule_candidates": [
                {"start": 3.0, "end": 3.2, "reason": "filler_word", "auto_applied": False},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={},
    )

    assert payload["candidate_risk_summary"] == {
        "total": {"low": 2, "medium": 0, "high": 1},
        "auto_apply": {"low": 2, "medium": 0, "high": 0},
        "manual_confirm": {"low": 0, "medium": 0, "high": 1},
    }
    assert payload["strategy_type"] == DEFAULT_STRATEGY_TYPE
    assert payload["strategy_profile"] == build_strategy_profile_payload()


def test_cut_analysis_payload_adds_default_strategy_profile_metadata() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    assert payload["strategy_type"] == "information_density"
    assert payload["strategy_profile"] == build_strategy_profile_payload()


def test_cut_analysis_payload_preserves_explicit_strategy_profile_metadata() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={"strategy_type": "step_demonstration"},
        source_name="demo.mp4",
        job_flow_mode="auto",
        strategy_profile={
            "schema": "legacy_strategy_profile",
            "strategy_type": "step_demonstration",
            "speech_priority": "medium",
        },
    )

    assert payload["strategy_type"] == "step_demonstration"
    assert payload["strategy_profile"]["schema"] == "legacy_strategy_profile"
    assert payload["strategy_profile"]["strategy_type"] == "step_demonstration"
    assert payload["strategy_profile"]["speech_priority"] == "medium"


def test_cut_analysis_payload_treats_low_risk_accepted_cuts_without_flag_as_auto_in_auto_mode() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {"start": 1.0, "end": 1.3, "reason": "silence"},
            ],
            "manual_editor_rule_candidates": [
                {"start": 2.0, "end": 2.8, "reason": "restart_retake", "auto_applied": False},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={},
    )

    assert payload["accepted_cuts"][0]["auto_applied"] is True
    assert payload["auto_apply_candidate_count"] == 1
    assert payload["manual_confirm_candidate_count"] == 1
    assert payload["candidate_risk_summary"] == {
        "total": {"low": 1, "medium": 0, "high": 1},
        "auto_apply": {"low": 1, "medium": 0, "high": 0},
        "manual_confirm": {"low": 0, "medium": 0, "high": 1},
    }


def test_cut_analysis_payload_keeps_review_gated_accepted_cut_as_manual_without_explicit_flag() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {
                    "start": 1.0,
                    "end": 1.3,
                    "reason": "silence",
                    "multimodal_review_required": True,
                },
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={},
    )

    assert payload["accepted_cuts"][0]["auto_applied"] is False
    assert payload["auto_apply_candidate_count"] == 0
    assert payload["manual_confirm_candidate_count"] == 1
    assert payload["candidate_risk_summary"] == {
        "total": {"low": 1, "medium": 0, "high": 0},
        "auto_apply": {"low": 0, "medium": 0, "high": 0},
        "manual_confirm": {"low": 1, "medium": 0, "high": 0},
    }


def test_cut_analysis_payload_auto_applies_low_risk_rule_candidates_in_auto_mode() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 0.4, "text_final": "嗯"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": False,
            "fillerSentenceTailEnabled": False,
            "catchphraseEnabled": False,
            "fillers": "嗯",
        },
    )

    candidate = next(item for item in payload["rule_candidates"] if item["reason"] == "filler_word")
    assert candidate["auto_applied"] is True
    assert candidate["match_surface_layer"] == "canonical"
    assert payload["auto_apply_candidate_count"] == 1
    assert payload["manual_confirm_candidate_count"] == 0


def test_cut_analysis_effective_applied_cuts_falls_back_to_auto_applied_rule_candidates() -> None:
    payload = {
        "accepted_cuts": [],
        "rule_candidates": [
            {"start": 1.0, "end": 1.3, "reason": "silence", "auto_applied": True},
            {"start": 2.0, "end": 2.4, "reason": "restart_retake", "auto_applied": False},
        ],
    }

    resolved = cut_analysis_effective_applied_cuts(payload)

    assert [(item["start"], item["end"], item["reason"], item["auto_applied"]) for item in resolved] == [
        (1.0, 1.3, "silence", True),
    ]
    assert resolved[0]["strategy_decision"]["decision"] == "auto_apply"


def test_cut_analysis_effective_applied_cuts_merges_distinct_auto_applied_rule_candidates_with_accepted_cuts() -> None:
    payload = {
        "accepted_cuts": [
            {"start": 1.0, "end": 1.3, "reason": "silence", "auto_applied": True},
        ],
        "rule_candidates": [
            {"start": 1.0, "end": 1.3, "reason": "silence", "auto_applied": True},
            {"start": 3.0, "end": 3.3, "reason": "filler_word", "auto_applied": True},
        ],
    }

    resolved = cut_analysis_effective_applied_cuts(payload)

    assert [(item["start"], item["end"], item["reason"], item["auto_applied"]) for item in resolved] == [
        (1.0, 1.3, "silence", True),
        (3.0, 3.3, "filler_word", True),
    ]
    assert [item["strategy_decision"]["decision"] for item in resolved] == ["auto_apply", "auto_apply"]


def test_cut_analysis_candidate_items_resolved_reuses_shared_auto_apply_contract() -> None:
    accepted_cuts, rule_candidates = cut_analysis_candidate_items(
        {
            "job_flow_mode": "auto",
            "accepted_cuts": [
                {"start": 1.0, "end": 1.3, "reason": "silence"},
                {
                    "start": 1.5,
                    "end": 1.8,
                    "reason": "silence",
                    "multimodal_review_required": True,
                },
            ],
            "rule_candidates": [
                {"start": 2.0, "end": 2.2, "reason": "filler_word"},
                {"start": 2.4, "end": 2.8, "reason": "restart_retake", "auto_applied": False},
            ],
        },
        resolved=True,
    )

    assert [item["auto_applied"] for item in accepted_cuts] == [True, False]
    assert [item["auto_applied"] for item in rule_candidates] == [True, False]
    assert [item["strategy_decision"]["decision"] for item in accepted_cuts] == ["auto_apply", "manual_confirm"]
    assert [item["strategy_decision"]["decision"] for item in rule_candidates] == ["auto_apply", "manual_confirm"]
    assert all(
        item["strategy_decision"]["schema"] == STRATEGY_CANDIDATE_DECISION_SCHEMA_VERSION
        for item in [*accepted_cuts, *rule_candidates]
    )


def test_cut_analysis_effective_applied_cuts_resolves_legacy_auto_payload_candidates() -> None:
    payload = {
        "job_flow_mode": "auto",
        "accepted_cuts": [
            {"start": 1.0, "end": 1.3, "reason": "silence"},
        ],
        "rule_candidates": [
            {"start": 1.0, "end": 1.3, "reason": "silence"},
            {"start": 3.0, "end": 3.3, "reason": "filler_word"},
            {"start": 4.0, "end": 4.5, "reason": "restart_retake"},
        ],
    }

    resolved = cut_analysis_effective_applied_cuts(payload)

    assert [(item["start"], item["end"], item["reason"]) for item in resolved] == [
        (1.0, 1.3, "silence"),
        (3.0, 3.3, "filler_word"),
    ]
    assert all(item["auto_applied"] is True for item in resolved)
    assert all(item["strategy_decision"]["decision"] == "auto_apply" for item in resolved)


def test_cut_analysis_payload_keeps_low_risk_rule_candidates_as_manual_in_manual_mode() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 0.4, "text_final": "嗯"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": False,
            "fillerSentenceTailEnabled": False,
            "catchphraseEnabled": False,
            "fillers": "嗯",
        },
    )

    candidate = next(item for item in payload["rule_candidates"] if item["reason"] == "filler_word")
    assert candidate["auto_applied"] is False
    assert candidate["match_surface_layer"] == "canonical"
    assert payload["auto_apply_candidate_count"] == 0
    assert payload["manual_confirm_candidate_count"] == 1


def test_cut_analysis_payload_keeps_reviewed_rule_candidate_out_of_rule_auto_apply_bucket() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "manual_editor_rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "filler_word",
                    "risk_level": "low",
                    "multimodal_review": {"verdict": "cut", "confidence": 0.88},
                }
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={},
    )

    candidate = payload["rule_candidates"][0]
    assert candidate["auto_applied"] is False
    assert candidate["strategy_decision"]["decision"] == "manual_confirm"
    assert candidate["strategy_decision"]["review_trigger"] == "multimodal_review_present"
    assert payload["auto_apply_candidate_count"] == 0
    assert payload["manual_confirm_candidate_count"] == 1
    assert payload["candidate_risk_summary"] == {
        "total": {"low": 1, "medium": 0, "high": 0},
        "auto_apply": {"low": 0, "medium": 0, "high": 0},
        "manual_confirm": {"low": 1, "medium": 0, "high": 0},
    }


def test_cut_analysis_payload_integrates_highlight_candidates_through_strategy_decision_gate() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "strategy_type": "event_highlight",
            "highlight_candidates": [
                {
                    "start_sec": 2.4,
                    "end_sec": 8.9,
                    "role": "detail",
                    "score": 1.27,
                    "reasons": ["命中 detail 段候选窗口", "窗口内存在强调候选"],
                    "source_item_indexes": [1, 2],
                    "source_emphasis_indexes": [0],
                }
            ],
        },
        source_name="highlight-demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={},
    )

    candidate = next(item for item in payload["rule_candidates"] if item["reason"] == "highlight_window")
    assert candidate["candidate_stage"] == "semantic_timeline_analysis"
    assert candidate["semantic_role"] == "highlight_candidate"
    assert candidate["semantic_source"] == "local_highlight_candidates"
    assert candidate["auto_applied"] is False
    assert candidate["risk_level"] == "medium"
    assert candidate["strategy_decision"]["decision"] == "manual_confirm"
    assert candidate["strategy_decision"]["strategy_type"] == "event_highlight"
    assert candidate["recommendation_reasons"] == ["命中 detail 段候选窗口", "窗口内存在强调候选"]
    assert candidate["provenance"] == {
        "producer": "local_highlight_candidates",
        "source_item_indexes": [1, 2],
        "source_emphasis_indexes": [0],
    }
    assert payload["auto_apply_candidate_count"] == 0
    assert payload["manual_confirm_candidate_count"] == 1
    assert payload["candidate_risk_summary"] == {
        "total": {"low": 0, "medium": 1, "high": 0},
        "auto_apply": {"low": 0, "medium": 0, "high": 0},
        "manual_confirm": {"low": 0, "medium": 1, "high": 0},
    }
    assert "semantic_timeline_analysis" in payload["candidate_sources"]


def test_cut_analysis_payload_integrates_multi_material_candidates_only_for_narrative_strategy() -> None:
    gated_payload = build_cut_analysis_payload(
        editorial_analysis={
            "strategy_type": "information_density",
            "multi_material_candidates": [
                {
                    "source_name": "detail-cut.mp4",
                    "role": "detail_support",
                    "score": 1.02,
                    "reasons": ["检测到辅助上传素材 detail-cut.mp4"],
                    "suggested_operation": "insert_into_detail_window",
                    "primary_source_name": "main.mp4",
                    "order_index": 1,
                }
            ],
        },
        source_name="commentary-demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={},
    )
    assert not any(item["reason"] == "multi_material_candidate" for item in gated_payload["rule_candidates"])

    payload = build_cut_analysis_payload(
        editorial_analysis={
            "strategy_type": "narrative_assembly",
            "multi_material_candidates": [
                {
                    "source_name": "detail-cut.mp4",
                    "role": "detail_support",
                    "score": 1.02,
                    "reasons": ["检测到辅助上传素材 detail-cut.mp4", "素材名更像细节或特写补充镜头"],
                    "suggested_operation": "insert_into_detail_window",
                    "primary_source_name": "main.mp4",
                    "order_index": 1,
                }
            ],
        },
        source_name="commentary-demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={},
    )

    candidate = next(item for item in payload["rule_candidates"] if item["reason"] == "multi_material_candidate")
    assert candidate["candidate_stage"] == "multi_material_assembly"
    assert candidate["auto_applied"] is False
    assert candidate["risk_level"] == "high"
    assert candidate["strategy_decision"]["decision"] == "manual_confirm"
    assert candidate["strategy_decision"]["strategy_type"] == "narrative_assembly"
    assert candidate["recommendation_reasons"] == ["检测到辅助上传素材 detail-cut.mp4", "素材名更像细节或特写补充镜头"]
    assert candidate["provenance"] == {
        "producer": "local_multi_material_candidates",
        "role": "detail_support",
        "primary_source_name": "main.mp4",
        "suggested_operation": "insert_into_detail_window",
        "order_index": 1,
    }
    assert payload["auto_apply_candidate_count"] == 0
    assert payload["manual_confirm_candidate_count"] == 1
    assert payload["candidate_risk_summary"] == {
        "total": {"low": 0, "medium": 0, "high": 1},
        "auto_apply": {"low": 0, "medium": 0, "high": 0},
        "manual_confirm": {"low": 0, "medium": 0, "high": 1},
    }
    assert "multi_material_assembly" in payload["candidate_sources"]


def test_cut_analysis_payload_attaches_strategy_decision_metadata_to_auto_apply_candidate() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 0.4, "text_final": "嗯"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": False,
            "fillerSentenceTailEnabled": False,
            "catchphraseEnabled": False,
            "fillers": "嗯",
        },
    )

    candidate = next(item for item in payload["rule_candidates"] if item["reason"] == "filler_word")
    assert candidate["auto_applied"] is True
    assert candidate["strategy_decision"]["schema"] == STRATEGY_CANDIDATE_DECISION_SCHEMA_VERSION
    assert candidate["strategy_decision"]["decision"] == "auto_apply"
    assert candidate["strategy_decision"]["auto_applied"] is True
    assert candidate["strategy_decision"]["strategy_type"] == "information_density"
    assert candidate["strategy_decision"]["accepted_cut"] is False
    assert candidate["strategy_decision"]["job_flow_mode"] == "auto"
    assert candidate["strategy_decision"]["risk_level"] == "low"
    assert candidate["strategy_decision"]["review_trigger"] is None
    assert candidate["strategy_decision"]["auto_apply_policy"] == "current_conservative_default"


def test_cut_analysis_payload_marks_sentence_tail_particles_without_treating_them_as_standalone() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "我们直接开箱吧"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": False,
            "fillerSentenceTailEnabled": True,
            "catchphraseEnabled": False,
            "fillers": "吧",
        },
    )

    candidates = payload["rule_candidates"]
    assert any(
        item["reason"] == "filler_word"
        and item["source_text"] == "吧"
        and item["filler_mode"] == "sentence_tail"
        for item in candidates
    )
    assert not any(
        item["reason"] == "filler_word"
        and item["source_text"] == "吧"
        and item["filler_mode"] == "standalone"
        for item in candidates
    )


def test_cut_analysis_pause_overlap_uses_spoken_rule_text_for_silence_gatekeeping() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "silence_segments": [
                {"start": 0.2, "end": 1.0, "duration_sec": 0.8, "source": "audio_vad"},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {
                "start_time": 0.0,
                "end_time": 1.3,
                "text_final": "啊",
                "transcript_text_raw": "今天你看这个",
            },
        ],
        smart_cut_rules={
            "pauseEnabled": True,
            "pauseThresholdSec": 0.8,
        },
    )

    assert not any(
        item["reason"] == "silence" and float(item["start"]) == 0.2 and float(item["end"]) == 1.0
        for item in payload["rule_candidates"]
    )


def test_cut_analysis_pause_overlap_blocks_when_spoken_surface_is_longer_than_timed_display_text() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "silence_segments": [
                {"start": 0.2, "end": 1.0, "duration_sec": 0.8, "source": "audio_vad"},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {
                "start_time": 0.0,
                "end_time": 1.3,
                "text_final": "高端手电",
                "transcript_text_raw": "今天你看这个高端手电",
                "words": [
                    {"word": "高", "start": 0.62, "end": 0.76},
                    {"word": "端", "start": 0.76, "end": 0.88},
                    {"word": "手", "start": 0.88, "end": 1.0},
                    {"word": "电", "start": 1.0, "end": 1.14},
                ],
            },
        ],
        smart_cut_rules={
            "pauseEnabled": True,
            "pauseThresholdSec": 0.8,
        },
    )

    assert not any(
        item["reason"] == "silence"
        and float(item["start"]) == 0.2
        and float(item["end"]) == 0.46
        for item in payload["rule_candidates"]
    )


def test_cut_analysis_payload_detects_standalone_fillers_from_raw_source_text_when_final_text_is_cleaned() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {
                "start_time": 0.0,
                "end_time": 1.0,
                "text_raw": "啊，今天我们开始",
                "text_norm": "啊，今天我们开始",
                "text_final": "今天我们开始",
            },
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": False,
            "fillerSentenceTailEnabled": False,
            "catchphraseEnabled": False,
            "fillers": "啊",
        },
    )

    candidates = payload["rule_candidates"]
    assert any(
        item["reason"] == "filler_word"
        and item["source_text"] == "啊"
        and item["filler_mode"] == "standalone"
        for item in candidates
    )


def test_cut_analysis_payload_does_not_project_hidden_raw_fillers_onto_timed_visible_text() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {
                "start_time": 2.32,
                "end_time": 4.0,
                "text_raw": "啊，呃，今天我们直奔主题啊，呃，",
                "text_norm": "啊，呃，今天我们直奔主题啊，呃，",
                "text_final": "今天我们直奔主题啊",
                "words": [
                    {"word": "今", "start": 2.64, "end": 2.76},
                    {"word": "天", "start": 2.76, "end": 2.88},
                    {"word": "我", "start": 2.88, "end": 3.0},
                    {"word": "们", "start": 3.0, "end": 3.12},
                    {"word": "直", "start": 3.12, "end": 3.24},
                    {"word": "奔", "start": 3.24, "end": 3.36},
                    {"word": "主", "start": 3.36, "end": 3.48},
                    {"word": "题", "start": 3.48, "end": 3.6},
                    {"word": "啊", "start": 3.6, "end": 3.78},
                ],
            },
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": True,
            "fillerSentenceTailEnabled": True,
            "catchphraseEnabled": False,
            "fillers": "啊,呃",
        },
    )

    filler_candidates = [item for item in payload["rule_candidates"] if item["reason"] == "filler_word"]
    assert not any(item["source_text"] == "呃" for item in filler_candidates)
    assert not any(item["source_text"] == "啊" and float(item["start"]) < 2.5 for item in filler_candidates)
    assert any(
        item["source_text"] == "啊"
        and item["filler_mode"] == "sentence_tail"
        and float(item["start"]) >= 3.55
        for item in filler_candidates
    )


def test_cut_analysis_payload_includes_match_surface_layer_for_generated_candidates() -> None:
    filler_payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "um let's begin"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": False,
            "fillerSentenceTailEnabled": False,
            "fillers": "um",
        },
    )

    filler = next(
        (
            item
            for item in filler_payload.get("rule_candidates") or []
            if str(item.get("reason") or "") == "filler_word"
        ),
        None,
    )
    assert filler is not None
    assert filler.get("match_surface_layer") == "canonical"
    assert filler.get("producer_id") == "speech_filler_candidate_producer"
    assert filler.get("strategy_applicability") == ["information_density"]

    catchphrase_payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "这个就是重点"},
        ],
        smart_cut_rules={
            "catchphraseEnabled": True,
            "catchphrases": "就是",
        },
    )

    catchphrase = next(
        (
            item
            for item in catchphrase_payload.get("rule_candidates") or []
            if str(item.get("reason") or "") == "catchphrase_phrase"
        ),
        None,
    )
    assert catchphrase is not None
    assert catchphrase.get("match_surface_layer") == "canonical"
    assert catchphrase.get("producer_id") == "speech_catchphrase_candidate_producer"
    assert catchphrase.get("strategy_applicability") == ["information_density"]

    low_signal_payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "其实也就这样吧"},
        ],
        smart_cut_rules={
            "smartDeleteEnabled": True,
        },
    )

    low_signal = next(
        (
            item
            for item in low_signal_payload.get("rule_candidates") or []
            if str(item.get("reason") or "") == "low_signal_subtitle"
        ),
        None,
    )
    assert low_signal is not None
    assert low_signal.get("match_surface_layer") == "canonical"
    assert low_signal.get("producer_id") == "semantic_trim_candidate_producer"
    assert low_signal.get("strategy_applicability") == ["information_density"]


def test_cut_analysis_payload_adds_candidate_producer_metadata_to_accepted_cuts() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {"start": 1.0, "end": 1.3, "reason": "silence", "auto_applied": True},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    accepted_cut = payload["accepted_cuts"][0]
    assert accepted_cut["producer_id"] == "pause_trim_candidate_producer"
    assert accepted_cut["strategy_applicability"] == ["information_density"]


def test_cut_analysis_payload_adds_backend_pause_rule_candidates() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "silence_segments": [
                {"start": 2.0, "end": 3.1, "duration_sec": 1.1, "source": "audio_vad"},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={
            "pauseEnabled": True,
            "pauseThresholdSec": 0.8,
        },
    )

    candidates = payload["rule_candidates"]
    assert any(
        item["reason"] == "silence"
        and item["candidate_stage"] == "manual_editor_smart_cut_rules"
        and item["start"] == 2.0
        and item["end"] == 3.1
        for item in candidates
    )


def test_manual_editor_cut_analysis_payload_refreshes_schema_artifact_with_current_rules() -> None:
    payload = _manual_editor_cut_analysis_payload(
        {
            "schema": "cut_analysis.v1",
            "accepted_cuts": [],
            "rule_candidates": [],
            "silence_segments": [
                {"start": 2.0, "end": 3.1, "duration_sec": 1.1, "source": "audio_vad"},
            ],
        },
        None,
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 0.4, "text_final": "嗯"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerContinuousEnabled": False,
            "pauseEnabled": True,
            "pauseThresholdSec": 0.8,
            "fillers": "嗯",
        },
    )

    assert any(item["reason"] == "filler_word" for item in payload["rule_candidates"])
    assert any(item["reason"] == "silence" for item in payload["rule_candidates"])


def test_manual_editor_cut_analysis_payload_drops_stale_backend_smart_cut_candidates() -> None:
    payload = _manual_editor_cut_analysis_payload(
        {
            "schema": "cut_analysis.v1",
            "accepted_cuts": [],
            "rule_candidates": [
                {
                    "start": 0.0,
                    "end": 0.12,
                    "reason": "filler_word",
                    "candidate_stage": "manual_editor_smart_cut_rules",
                    "source_text": "嗯",
                    "filler_mode": "standalone",
                },
                {
                    "start": 2.0,
                    "end": 2.3,
                    "reason": "repeated_speech",
                    "candidate_stage": "manual_editor_full_transcript",
                },
            ],
            "silence_segments": [
                {"start": 2.0, "end": 3.1, "duration_sec": 1.1, "source": "audio_vad"},
            ],
        },
        None,
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "嗯我们开始"},
        ],
        smart_cut_rules={
            "fillerEnabled": False,
            "pauseEnabled": False,
        },
    )

    assert len(payload["rule_candidates"]) == 1
    stale_still_present = payload["rule_candidates"][0]
    assert stale_still_present["reason"] == "repeated_speech"
    assert stale_still_present["candidate_stage"] == "manual_editor_full_transcript"
    assert not any(
        item["reason"] == "filler_word" and item.get("candidate_stage") == "manual_editor_smart_cut_rules"
        for item in payload["rule_candidates"]
    )


def test_manual_editor_cut_analysis_payload_drops_repeated_speech_when_toggle_closed() -> None:
    payload = _manual_editor_cut_analysis_payload(
        {
            "schema": "cut_analysis.v1",
            "accepted_cuts": [],
            "manual_editor_rule_candidates": [
                {
                    "start": 0.0,
                    "end": 0.2,
                    "reason": "repeated_speech",
                    "candidate_stage": "manual_editor_full_transcript",
                },
                {
                    "start": 2.0,
                    "end": 2.4,
                    "reason": "silence",
                    "candidate_stage": "manual_editor_full_transcript",
                },
            ],
            "silence_segments": [],
        },
        None,
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[],
        smart_cut_rules={
            "repeatedEnabled": False,
            "fillerEnabled": False,
            "pauseEnabled": False,
            "catchphraseEnabled": False,
            "smartDeleteEnabled": True,
        },
    )

    reasons = {item.get("reason") for item in payload["rule_candidates"]}
    assert "repeated_speech" not in reasons
    assert "silence" in reasons


def test_manual_editor_cut_analysis_payload_falls_back_to_manual_editor_rule_candidates_when_rule_candidates_schema_invalid() -> None:
    payload = _manual_editor_cut_analysis_payload(
        {
            "schema": "cut_analysis.v1",
            "accepted_cuts": [],
            "rule_candidates": "legacy_scalar_payload",
            "manual_editor_rule_candidates": [
                {
                    "start": 0.1,
                    "end": 0.2,
                    "reason": "repeated_speech",
                    "candidate_stage": "manual_editor_full_transcript",
                },
                {
                    "start": 2.0,
                    "end": 2.4,
                    "reason": "silence",
                    "candidate_stage": "manual_editor_full_transcript",
                },
            ],
            "silence_segments": [],
        },
        None,
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[],
        smart_cut_rules={
            "repeatedEnabled": False,
            "fillerEnabled": False,
            "pauseEnabled": False,
            "catchphraseEnabled": False,
            "smartDeleteEnabled": True,
        },
    )

    reasons = {item.get("reason") for item in payload["rule_candidates"]}
    assert "repeated_speech" not in reasons
    assert "silence" in reasons


def test_build_cut_analysis_payload_preserves_smart_rule_candidate_metadata() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "schema": "cut_analysis.v1",
            "rule_candidates": [
                {
                    "start": 0.0,
                    "end": 0.12,
                    "reason": "filler_word",
                    "candidate_stage": "manual_editor_smart_cut_rules",
                    "source_text": "嗯",
                    "filler_mode": "standalone",
                    "rule_id": "cached-filler-001",
                    "risk_level": "high",
                    "match_surface": "cached-surface",
                    "match_surface_layer": "raw",
                    "auto_applied": False,
                }
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "嗯我们开始"},
        ],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
            "fillerSentenceHeadEnabled": True,
            "fillers": "嗯",
        },
    )

    assert len(payload["rule_candidates"]) == 1
    assert payload["rule_candidates"][0]["rule_id"] == "cached-filler-001"
    assert payload["rule_candidates"][0]["risk_level"] == "high"
    assert payload["rule_candidates"][0]["match_surface"] == "cached-surface"
    assert payload["rule_candidates"][0]["match_surface_layer"] == "raw"


def test_build_cut_analysis_payload_backfills_repeated_speech_metadata_from_legacy_candidate() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "schema": "cut_analysis.v1",
            "rule_candidates": [
                {
                    "start": 1.2,
                    "end": 1.46,
                    "reason": "repeated_speech",
                    "candidate_stage": "manual_editor_full_transcript",
                    "signals": ["partial_repeated_speech", "unit:这个啊"],
                }
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[],
        smart_cut_rules={"repeatedEnabled": True},
    )

    assert len(payload["rule_candidates"]) == 1
    candidate = payload["rule_candidates"][0]
    assert candidate["reason"] == "repeated_speech"
    assert candidate["candidate_stage"] == "manual_editor_full_transcript"
    assert candidate["source_text"] == "这个啊"
    assert candidate["match_surface"] == "这个啊"
    assert candidate["match_surface_layer"] == "raw"
    assert candidate["risk_level"] == "medium"
    assert candidate["rule_id"] == "repeated_speech:1.200:1.460:这个啊"


def test_build_cut_analysis_payload_backfills_silence_metadata_for_accepted_cuts() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {
                    "start": 10.0,
                    "end": 10.8,
                    "reason": "silence",
                    "boundary_keep_energy": 1.2,
                }
            ]
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={"pauseEnabled": True},
    )

    assert len(payload["accepted_cuts"]) == 1
    accepted = payload["accepted_cuts"][0]
    assert accepted["source_text"] == "silence"
    assert accepted["match_surface"] == "silence"
    assert accepted["match_surface_layer"] == "raw"
    assert accepted["risk_level"] == "low"
    assert accepted["rule_id"] == "silence:10.000:10.800:silence"


def test_manual_editor_rule_segments_use_registry_defaults_for_repeated_speech() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "schema": "cut_analysis.v1",
            "rule_candidates": [
                {
                    "start": 3.0,
                    "end": 3.48,
                    "reason": "repeated_speech",
                    "candidate_stage": "manual_editor_full_transcript",
                    "signals": ["partial_repeated_speech", "unit:这个啊"],
                }
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="manual",
        source_subtitles=[],
        smart_cut_rules={"repeatedEnabled": True},
    )

    segments = _manual_editor_rule_segments(payload)

    assert len(segments) == 1
    assert segments[0].kind == "repeated"
    assert segments[0].rule_id == "repeated_speech:3.000:3.480:这个啊"
    assert segments[0].risk_level == "medium"
    assert segments[0].match_surface == "这个啊"
    assert segments[0].match_surface_layer == "raw"


def test_variant_timeline_bundle_carries_refine_decision_plan() -> None:
    bundle = _build_variant_timeline_bundle(
        editorial_timeline_id="timeline-1",
        render_plan_timeline_id="timeline-2",
        keep_segments=[{"start": 1.0, "end": 3.0}],
        editorial_analysis={"accepted_cuts": [{"start": 3.0, "end": 4.0, "reason": "silence"}]},
        cut_analysis={
            "schema": "cut_analysis.v1",
            "accepted_cuts": [{"start": 5.0, "end": 6.0, "reason": "restart_retake"}],
            "candidate_count": 1,
            "accepted_cut_count": 1,
            "rule_candidate_count": 0,
            "manual_confirm_candidate_count": 0,
        },
        refine_decision_plan={
            "schema": "refine_decision_plan.v1",
            "mode": "manual_refine",
            "keep_segments": [{"start": 1.0, "end": 3.0}],
            "candidate_summary": {"total": 2, "auto_apply": 1, "manual_confirm": 1},
            "smart_cut_rules": {"pauseEnabled": True, "pauseThresholdSec": 0.8},
        },
        render_plan={"timeline_analysis": {"hook_end_sec": 2.5}},
        variants={"plain": {"segments": []}},
    )

    assert bundle["timeline_rules"]["refine_decision_plan"] == {
        "schema": "refine_decision_plan.v1",
        "mode": "manual_refine",
        "keep_segments": [{"start": 1.0, "end": 3.0}],
        "candidate_summary": {"total": 2, "auto_apply": 1, "manual_confirm": 1},
        "smart_cut_rules": {"pauseEnabled": True, "pauseThresholdSec": 0.8},
    }
    assert bundle["timeline_rules"]["cut_analysis"] == {
        "schema": "cut_analysis.v1",
        "accepted_cuts": [{"start": 5.0, "end": 6.0, "reason": "restart_retake"}],
        "candidate_count": 1,
        "accepted_cut_count": 1,
        "rule_candidate_count": 0,
        "manual_confirm_candidate_count": 0,
    }
    assert bundle["timeline_rules"]["diagnostics"]["high_risk_cuts"] == []
    assert bundle["timeline_rules"]["diagnostics"]["cut_analysis_summary"] == {
        "candidate_count": 1,
        "accepted_cut_count": 1,
        "rule_candidate_count": 0,
        "auto_apply_candidate_count": 0,
        "manual_confirm_candidate_count": 0,
        "candidate_risk_summary": {},
    }
    assert bundle["timeline_rules"]["diagnostics"]["refine_decision_summary"] == {
        "mode": "manual_refine",
        "keep_segment_count": 1,
        "candidate_total": 2,
        "candidate_auto_apply": 1,
        "candidate_manual_confirm": 1,
        "rule_auto_apply_cut_count": 0,
        "multimodal_auto_apply_cut_count": 0,
        "risk_levels": {},
    }
    packaging_timeline = dict(bundle["timeline_rules"]["packaging_timeline"])
    assert packaging_timeline.pop("hyperframes")["schema"] == "roughcut.hyperframes.plan.v1"
    assert packaging_timeline == {
        "timeline_analysis": {"hook_end_sec": 2.5},
        "editing_skill": {},
        "section_choreography": {},
        "subtitles": {},
        "packaging": {
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        "editing_accents": {},
    }


def test_variant_timeline_bundle_reuses_local_packaging_timeline_analysis_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "_validate_variant_timeline_bundle",
        lambda _bundle, *, packaging_timeline=None: {"status": "ok", "issues": []},
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_analysis",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local packaging timeline analysis payload")),
    )

    bundle = _build_variant_timeline_bundle(
        editorial_timeline_id="timeline-1",
        render_plan_timeline_id="timeline-2",
        keep_segments=[{"start": 1.0, "end": 3.0}],
        editorial_analysis={},
        cut_analysis={},
        refine_decision_plan={},
        render_plan={"timeline_analysis": {"hook_end_sec": 2.5}},
        variants={"plain": {"segments": []}},
    )

    assert bundle["timeline_rules"]["diagnostics"]["review_flags"] == {
        "review_recommended": False,
        "review_reasons": [],
        "hook_end_sec": 2.5,
        "cta_start_sec": None,
    }


def test_variant_timeline_bundle_reuses_passed_packaging_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "_validate_variant_timeline_bundle",
        lambda _bundle, *, packaging_timeline=None: {"status": "ok", "issues": []},
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "build_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse passed packaging timeline")),
    )

    bundle = _build_variant_timeline_bundle(
        editorial_timeline_id="timeline-1",
        render_plan_timeline_id="timeline-2",
        keep_segments=[{"start": 1.0, "end": 3.0}],
        editorial_analysis={},
        cut_analysis={},
        refine_decision_plan={},
        render_plan=None,
        packaging_timeline={"timeline_analysis": {"hook_end_sec": 2.5}},
        variants={"plain": {"segments": []}},
    )

    assert bundle["timeline_rules"]["packaging_timeline"] == {"timeline_analysis": {"hook_end_sec": 2.5}}
    assert bundle["timeline_rules"]["diagnostics"]["review_flags"]["hook_end_sec"] == 2.5


def test_variant_timeline_bundle_reuses_local_packaging_timeline_for_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _validate(_bundle: dict[str, Any], *, packaging_timeline: dict[str, Any] | None = None) -> dict[str, Any]:
        captured["packaging_timeline"] = packaging_timeline
        return {"status": "ok", "issues": []}

    monkeypatch.setattr(
        pipeline_steps_module,
        "_validate_variant_timeline_bundle",
        _validate,
    )

    bundle = _build_variant_timeline_bundle(
        editorial_timeline_id="timeline-1",
        render_plan_timeline_id="timeline-2",
        keep_segments=[{"start": 1.0, "end": 3.0}],
        editorial_analysis={},
        cut_analysis={},
        refine_decision_plan={},
        render_plan=None,
        packaging_timeline={"timeline_analysis": {"hook_end_sec": 2.5}},
        variants={"plain": {"segments": []}},
    )

    assert captured["packaging_timeline"] == {"timeline_analysis": {"hook_end_sec": 2.5}}
    assert bundle["validation"] == {"status": "ok", "issues": []}


def test_variant_timeline_bundle_allows_diagnostics_only_payload_without_render_variants() -> None:
    bundle = _build_variant_timeline_bundle(
        editorial_timeline_id="timeline-1",
        render_plan_timeline_id="timeline-2",
        keep_segments=[{"start": 1.0, "end": 3.0}],
        editorial_analysis={"llm_cut_review": {"reviewed": True, "candidate_count": 1}},
        cut_analysis={
            "schema": "cut_analysis.v1",
            "accepted_cuts": [{"start": 5.0, "end": 6.0, "reason": "restart_retake", "boundary_keep_energy": 1.2}],
            "manual_confirm_candidate_count": 2,
        },
        refine_decision_plan={
            "schema": "refine_decision_plan.v1",
            "mode": "auto_refine",
            "candidate_summary": {"total": 2, "auto_apply": 0, "manual_confirm": 2},
        },
        render_plan={
            "timeline_analysis": {"hook_end_sec": 2.5},
            "editing_skill": {"key": "unboxing_standard"},
        },
        variants={},
    )

    assert bundle["variants"] == {}
    assert bundle["timeline_rules"]["diagnostics"]["high_risk_cuts"] == []
    assert bundle["timeline_rules"]["diagnostics"]["llm_cut_review"] == {
        "reviewed": True,
        "candidate_count": 1,
        "decision_count": 0,
        "restored_cut_count": 0,
        "cached": False,
        "provider": "",
        "model": "",
        "summary": "",
        "error": "",
        "timeout": False,
    }
    assert bundle["validation"] == {"status": "ok", "issues": []}


def test_resolve_editorial_analysis_payload_reuses_caller_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "editorial_timeline_analysis",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse caller analysis payload")),
    )

    resolved = _resolve_editorial_analysis_payload(
        {"analysis": {"ignored": True}},
        analysis={"accepted_cuts": [{"start": 1.0, "end": 2.0, "reason": "silence"}]},
    )
    resolved["accepted_cuts"][0]["reason"] = "mutated"

    assert _resolve_editorial_analysis_payload(
        {"analysis": {"ignored": True}},
        analysis={"accepted_cuts": [{"start": 1.0, "end": 2.0, "reason": "silence"}]},
    ) == {
        "accepted_cuts": [{"start": 1.0, "end": 2.0, "reason": "silence"}]
    }


def test_variant_timeline_editorial_context_reuses_local_payload_readers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def _analysis(payload: dict[str, object]) -> dict[str, object]:
        calls.append(("analysis", str(payload.get("label") or "")))
        return {"label": payload.get("label")}

    def _segments(payload: dict[str, object]) -> list[dict[str, object]]:
        calls.append(("segments", str(payload.get("label") or "")))
        return [{"label": payload.get("label")}]

    monkeypatch.setattr(pipeline_steps_module, "editorial_timeline_analysis", _analysis)
    monkeypatch.setattr(pipeline_steps_module, "editorial_timeline_segments", _segments)

    context = _variant_timeline_editorial_context(
        {"label": "plain"},
        packaged_editorial_timeline={"label": "packaged"},
    )

    assert context == {
        "analysis": {"label": "plain"},
        "plain_segments": [{"label": "plain"}],
        "packaged_segments": [{"label": "packaged"}],
    }
    assert sorted(calls) == [
        ("analysis", "plain"),
        ("segments", "packaged"),
        ("segments", "plain"),
    ]


def test_variant_timeline_editorial_context_reuses_caller_plain_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def _analysis(payload: dict[str, object]) -> dict[str, object]:
        calls.append(("analysis", str(payload.get("label") or "")))
        return {"label": payload.get("label")}

    def _segments(payload: dict[str, object]) -> list[dict[str, object]]:
        calls.append(("segments", str(payload.get("label") or "")))
        return [{"label": payload.get("label")}]

    monkeypatch.setattr(pipeline_steps_module, "editorial_timeline_analysis", _analysis)
    monkeypatch.setattr(pipeline_steps_module, "editorial_timeline_segments", _segments)

    context = _variant_timeline_editorial_context(
        {"label": "plain"},
        packaged_editorial_timeline={"label": "packaged"},
        plain_segments=[{"label": "provided"}],
    )

    assert context == {
        "analysis": {"label": "plain"},
        "plain_segments": [{"label": "provided"}],
        "packaged_segments": [{"label": "packaged"}],
    }
    assert calls == [
        ("analysis", "plain"),
        ("segments", "packaged"),
    ]


def test_variant_timeline_editorial_context_reuses_caller_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "editorial_timeline_analysis",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse caller analysis")),
    )

    context = _variant_timeline_editorial_context(
        {"label": "plain"},
        analysis={"accepted_cuts": [{"start": 1.0, "end": 2.0, "reason": "silence"}]},
        packaged_editorial_timeline={"label": "packaged"},
        plain_segments=[{"label": "provided"}],
    )

    assert context["analysis"] == {"accepted_cuts": [{"start": 1.0, "end": 2.0, "reason": "silence"}]}


def test_validate_variant_timeline_bundle_reuses_local_normalized_packaging_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_analysis",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local timeline_analysis payload")),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_editing_skill",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local editing_skill payload")),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "packaging_timeline_section_choreography",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse local section_choreography payload")),
    )
    assert not hasattr(pipeline_steps_module, "packaging_timeline_assets")
    assert not hasattr(pipeline_steps_module, "packaging_timeline_editing_accents")

    assert _validate_variant_timeline_bundle(
        {
            "variants": {
                "plain": {
                    "media": {"duration_sec": 3.0},
                    "subtitle_events": [{"start_time": 0.0, "end_time": 1.0, "text": "demo"}],
                }
            },
            "timeline_rules": {
                "timeline_analysis": {},
                "editing_skill": {"key": "knowledge_explainer"},
                "section_choreography": {"sections": [{"start_sec": 0.0, "end_sec": 3.0}]},
                "packaging": {"intro": {"path": "intro.mp4"}},
                "editing_accents": {"style": "smart_effect_punch"},
            },
        }
    ) == {"status": "ok", "issues": []}


def test_validate_variant_timeline_bundle_reuses_passed_packaging_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "resolve_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse passed packaging timeline")),
    )

    assert _validate_variant_timeline_bundle(
        {
            "variants": {
                "plain": {
                    "media": {"duration_sec": 3.0},
                    "subtitle_events": [{"start_time": 0.0, "end_time": 1.0, "text": "demo"}],
                }
            },
            "timeline_rules": {"diagnostics": {}},
        },
        packaging_timeline={
            "timeline_analysis": {},
            "editing_skill": {"key": "knowledge_explainer"},
            "section_choreography": {"sections": [{"start_sec": 0.0, "end_sec": 3.0}]},
            "packaging": {"intro": {"path": "intro.mp4"}},
            "editing_accents": {"style": "smart_effect_punch"},
        },
    ) == {"status": "ok", "issues": []}


def test_validate_variant_timeline_bundle_reuses_nested_bundle_packaging_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pipeline_steps_module,
        "resolve_packaging_timeline_payload",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse nested bundle packaging timeline")),
    )

    assert _validate_variant_timeline_bundle(
        {
            "variants": {
                "plain": {
                    "media": {"duration_sec": 3.0},
                    "subtitle_events": [{"start_time": 0.0, "end_time": 1.0, "text": "demo"}],
                }
            },
            "timeline_rules": {
                "packaging_timeline": {
                    "timeline_analysis": {},
                    "editing_skill": {"key": "knowledge_explainer"},
                    "section_choreography": {"sections": [{"start_sec": 0.0, "end_sec": 3.0}]},
                    "packaging": {"intro": {"path": "intro.mp4"}},
                    "editing_accents": {"style": "smart_effect_punch"},
                },
                "diagnostics": {},
            },
        }
    ) == {"status": "ok", "issues": []}


def test_edit_review_bundle_payload_carries_cut_analysis_and_refine_decision_plan() -> None:
    payload = _build_edit_review_bundle_payload(
        job_flow_mode="auto",
        source_name="demo.mp4",
        content_profile={"topic_fact_confirmation": {"status": "confirmed"}},
        source_timeline_contract={"duration_sec": 12.0},
        subtitle_source_projection_validation={"status": "ok"},
        automatic_gate={"eligible": True},
        edit_decision={"segments": [{"type": "keep", "start": 0.0, "end": 2.0}]},
        full_subtitles=[{"text_final": "原始字幕"}],
        edited_subtitles=[{"text_final": "输出字幕"}],
        cut_analysis={"schema": "cut_analysis.v1", "candidate_count": 2},
        refine_decision_plan={"schema": "refine_decision_plan.v1", "mode": "auto_refine"},
        multimodal_trim_review={"schema": "multimodal_trim_review.v1", "candidate_count": 1},
    )

    assert payload["topic_fact_confirmation"] == {"status": "confirmed"}
    assert payload["cut_analysis"] == {"schema": "cut_analysis.v1", "candidate_count": 2}
    assert payload["refine_decision_plan"] == {"schema": "refine_decision_plan.v1", "mode": "auto_refine"}
    assert payload["multimodal_trim_review"] == {"schema": "multimodal_trim_review.v1", "candidate_count": 1}
    assert payload["full_subtitles"] == [{"text_final": "原始字幕"}]
    assert payload["edited_subtitles"] == [{"text_final": "输出字幕"}]


def test_manual_editor_restore_frontend_managed_auto_cuts_accepts_cut_analysis_payload() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {"start": 1.0, "end": 1.3, "reason": "filler_word", "auto_applied": True},
                {"start": 3.0, "end": 3.5, "reason": "silence", "auto_applied": True},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    assert _manual_editor_restore_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    ) == [{"start": 0.0, "end": 5.0}]


def test_manual_editor_apply_frontend_managed_auto_cuts_restores_effective_render_ranges() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {"start": 1.0, "end": 1.3, "reason": "filler_word", "auto_applied": True},
                {"start": 3.0, "end": 3.5, "reason": "silence", "auto_applied": True},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    assert _manual_editor_apply_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    ) == [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 3.0}, {"start": 3.5, "end": 5.0}]


def test_manual_editor_frontend_managed_auto_cuts_prefer_accepted_cuts_over_preview_rule_candidates() -> None:
    payload = {
        "accepted_cuts": [
            {"start": 1.0, "end": 1.3, "reason": "silence"},
        ],
        "rule_candidates": [
            {"start": 1.0, "end": 1.3, "reason": "silence", "auto_applied": True},
            {"start": 3.0, "end": 3.3, "reason": "silence", "auto_applied": True, "candidate_stage": "manual_editor_smart_cut_rules"},
        ],
    }

    assert _manual_editor_apply_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    ) == [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}]


def test_manual_editor_frontend_managed_auto_cuts_fall_back_to_rule_candidates_when_accepted_cuts_missing() -> None:
    payload = {
        "accepted_cuts": [],
        "rule_candidates": [
            {"start": 1.0, "end": 1.3, "reason": "silence", "auto_applied": True, "candidate_stage": "manual_editor_smart_cut_rules"},
        ],
    }

    assert _manual_editor_apply_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    ) == [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}]


def test_manual_editor_frontend_managed_auto_cuts_ignore_accepted_ranges_without_current_deleted_overlap() -> None:
    payload = {
        "accepted_cuts": [
            {"start": 1.0, "end": 1.3, "reason": "silence"},
        ],
        "rule_candidates": [
            {"start": 3.0, "end": 3.3, "reason": "silence", "auto_applied": True, "candidate_stage": "manual_editor_smart_cut_rules"},
        ],
    }

    assert _manual_editor_restore_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 3.0}, {"start": 3.3, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    ) == [{"start": 0.0, "end": 3.0}, {"start": 3.3, "end": 5.0}]

    assert _manual_editor_apply_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
        current_keep_segments=[{"start": 0.0, "end": 3.0}, {"start": 3.3, "end": 5.0}],
    ) == [{"start": 0.0, "end": 5.0}]


def test_manual_editor_frontend_managed_auto_cuts_keep_accepted_ranges_when_current_deleted_overlap() -> None:
    payload = {
        "accepted_cuts": [
            {"start": 1.0, "end": 1.3, "reason": "silence"},
        ],
        "rule_candidates": [
            {"start": 3.0, "end": 3.3, "reason": "silence", "auto_applied": True, "candidate_stage": "manual_editor_smart_cut_rules"},
        ],
    }

    assert _manual_editor_restore_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    ) == [{"start": 0.0, "end": 5.0}]

    assert _manual_editor_apply_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
        current_keep_segments=[{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}],
    ) == [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}]


def test_manual_editor_restore_frontend_managed_auto_cuts_preserves_adjacent_manual_gap() -> None:
    payload = {
        "accepted_cuts": [
            {"start": 41.07, "end": 42.16, "reason": "silence"},
        ],
    }

    assert _manual_editor_restore_frontend_managed_auto_cuts(
        [{"start": 40.62, "end": 41.07}, {"start": 42.21, "end": 45.99}],
        analysis_payload=payload,
        source_duration_sec=45.99,
    ) == [{"start": 40.62, "end": 42.16}, {"start": 42.21, "end": 45.99}]


def test_manual_editor_apply_semantics_keep_subtitle_only_scope_when_frontend_auto_cuts_are_unchanged() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {"start": 1.0, "end": 1.3, "reason": "filler_word", "auto_applied": True},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    previous_keep_segments = _manual_editor_restore_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    )
    requested_keep_segments = [{"start": 0.0, "end": 5.0}]
    effective_keep_segments = _manual_editor_apply_frontend_managed_auto_cuts(
        requested_keep_segments,
        analysis_payload=payload,
        source_duration_sec=5.0,
    )

    plan = _manual_editor_change_plan(
        previous_keep_segments=previous_keep_segments,
        next_keep_segments=requested_keep_segments,
        subtitle_overrides=[{"index": 0, "text_final": "new"}],
    )

    assert previous_keep_segments == [{"start": 0.0, "end": 5.0}]
    assert effective_keep_segments == [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}]
    assert plan["change_scope"] == "subtitle_only"
    assert plan["timeline_changed"] is False


def test_manual_editor_frontend_managed_auto_cuts_keep_low_risk_catchphrase_ranges() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [
                {"start": 1.0, "end": 1.4, "reason": "catchphrase_phrase", "auto_applied": True},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    restored_keep_segments = _manual_editor_restore_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 1.0}, {"start": 1.4, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    )
    effective_keep_segments = _manual_editor_apply_frontend_managed_auto_cuts(
        [{"start": 0.0, "end": 5.0}],
        analysis_payload=payload,
        source_duration_sec=5.0,
    )

    assert restored_keep_segments == [{"start": 0.0, "end": 5.0}]
    assert effective_keep_segments == [{"start": 0.0, "end": 1.0}, {"start": 1.4, "end": 5.0}]


def test_manual_editor_silence_payloads_can_come_from_cut_analysis_schema() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "silence_segments": [
                {"start": 1.23456, "end": 2.5, "source": "preview_vad"},
                {"start": 3.0, "end": 3.03, "source": "preview_vad"},
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    normalized = [
        item
        for item in [_manual_editor_silence_payload(segment) for segment in payload.get("silence_segments") or []]
        if item is not None
    ]

    assert [(item.start, item.end, item.source) for item in normalized] == [(1.235, 2.5, "preview_vad")]


def test_manual_editor_rule_segments_expose_backend_catchphrase_and_filler_mode() -> None:
    segments = _manual_editor_rule_segments(
        {
            "accepted_cuts": [],
            "rule_candidates": [
                {
                    "start": 1.0,
                    "end": 1.2,
                    "reason": "filler_word",
                    "candidate_stage": "manual_editor_smart_cut_rules",
                    "source_text": "嗯",
                    "filler_mode": "standalone",
                    "score": 0.92,
                },
                {
                    "start": 2.0,
                    "end": 2.4,
                    "reason": "catchphrase_phrase",
                    "candidate_stage": "manual_editor_smart_cut_rules",
                    "source_text": "就是",
                    "score": 0.74,
                },
            ],
        }
    )

    assert [(item.kind, item.source_text, item.filler_mode) for item in segments] == [
        ("filler", "嗯", "standalone"),
        ("catchphrase", "就是", None),
    ]


def test_manual_editor_rule_segments_infer_legacy_filler_modes_from_signals() -> None:
    segments = _manual_editor_rule_segments(
        {
            "accepted_cuts": [],
            "manual_editor_rule_candidates": [
                {
                    "start": 1.0,
                    "end": 1.2,
                    "reason": "filler_word",
                    "candidate_stage": "manual_editor_full_transcript",
                    "signals": ["pure_filler", "subtitle_rule_no_transcript_guard"],
                },
                {
                    "start": 2.0,
                    "end": 2.16,
                    "reason": "filler_word",
                    "candidate_stage": "manual_editor_full_transcript",
                    "signals": ["partial_filler", "token:嗯", "subtitle_rule_confirmed_by_transcript_filler"],
                },
            ],
        }
    )

    assert [(item.kind, item.filler_mode, item.match_surface, item.source_text) for item in segments] == [
        ("filler", "standalone", "standalone", None),
        ("filler", "sentence_head", "sentence_head", "嗯"),
    ]


def test_manual_editor_rule_segments_expose_backend_pause_candidates() -> None:
    segments = _manual_editor_rule_segments(
        {
            "accepted_cuts": [],
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 3.1,
                    "reason": "silence",
                    "candidate_stage": "manual_editor_smart_cut_rules",
                    "score": 0.81,
                },
            ],
        }
    )

    assert [(item.kind, item.start, item.end, item.source) for item in segments] == [
        ("pause", 2.0, 3.1, "manual_editor_rule_candidate"),
    ]


def test_backend_smart_cut_candidates_skip_ultra_short_bridge_clauses() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 0.9, "text_final": "然后呢"},
            {"start_time": 1.0, "end_time": 2.2, "text_final": "EDC17亮度一千五流明"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
    )

    low_signal = [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    ]

    assert low_signal == []


def test_backend_smart_cut_candidates_do_not_mark_short_actionable_clause_as_low_signal() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "解锁以后呢"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "拿这个三"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
    )

    low_signal = [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    ]

    assert low_signal == []


def test_backend_smart_cut_candidates_keep_longer_low_signal_clause_reviewable() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "其实也就这样吧"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
    )

    low_signal = [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    ]

    assert len(low_signal) == 1
    assert low_signal[0]["source_text"] == "其实也就这样吧"


def test_backend_smart_cut_candidates_respect_disabled_low_signal_reason() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "其实也就这样吧"},
        ],
        smart_cut_rules={
            "smartDeleteEnabled": True,
            "disabledSmartDeleteReasons": ["low_signal_subtitle"],
        },
    )

    low_signal = [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    ]

    assert low_signal == []


def test_backend_smart_cut_candidates_filter_disabled_existing_smart_delete_reason() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={
            "manual_editor_rule_candidates": [
                {
                    "start": 3.0,
                    "end": 4.2,
                    "reason": "restart_retake",
                    "candidate_stage": "manual_editor_smart_cut_rules",
                    "score": 0.8,
                },
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[],
        smart_cut_rules={
            "smartDeleteEnabled": True,
            "disabledSmartDeleteReasons": ["restart_retake"],
        },
    )

    assert [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "restart_retake"
    ] == []


def test_backend_smart_cut_low_signal_candidates_use_corrected_semantic_preview_text() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {
                "start_time": 0.0,
                "end_time": 1.1,
                "text_raw": "其实也就酱样吧",
                "transcript_text_raw": "其实也就酱样吧",
                "transcript_text": "其实也就这样吧",
            },
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
    )

    low_signal = [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    ]

    assert len(low_signal) == 1
    assert low_signal[0]["source_text"] == "其实也就这样吧"


def test_backend_low_signal_candidates_mark_multimodal_review_when_visual_hint_overlaps() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "其实也就这样吧"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
        content_profile={
            "video_understanding": {
                "segment_understanding": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "role": "detail_showcase",
                        "keep_priority": "high",
                        "confidence": 0.91,
                    }
                ]
            }
        },
    )

    low_signal = [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    ]

    assert len(low_signal) == 1
    assert low_signal[0]["multimodal_review_required"] is True
    assert low_signal[0]["multimodal_keep_priority"] == "high"
    assert low_signal[0]["multimodal_roles"] == ["detail_showcase"]


def test_backend_smart_cut_candidates_do_not_mark_contextual_bridge_clause_as_low_signal() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.0, "text_final": "这个模式对啊亮低就是低"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "其实也就这样吧"},
            {"start_time": 2.0, "end_time": 3.0, "text_final": "而且它的这个UV的功能啊"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
        content_profile={"subject_type": "EDC手电", "subject_brand": "NITECORE", "subject_model": "EDC17"},
    )

    low_signal = [
        item
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    ]

    assert low_signal == []


def test_backend_smart_cut_candidates_do_not_mark_example_chain_fragment_as_low_signal() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "所以说它的揣在兜里非常轻便"},
            {"start_time": 1.1, "end_time": 2.3, "text_final": "所以说为什么我平时比如临时出个门遛个狗啊"},
            {"start_time": 2.3, "end_time": 3.5, "text_final": "或者说简单的这个短途的通勤啊"},
            {"start_time": 3.5, "end_time": 4.3, "text_final": "门都会带它很实用"},
            {"start_time": 4.3, "end_time": 5.2, "text_final": "而且它的这个UV的功能啊"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
        content_profile={"subject_type": "EDC手电", "subject_brand": "NITECORE", "subject_model": "EDC17 EDC37"},
    )

    low_signal_texts = {
        str(item.get("source_text") or "")
        for item in payload.get("rule_candidates") or []
        if str(item.get("reason") or "") == "low_signal_subtitle"
    }

    assert "所以说为什么我平时比如临时出个门遛个狗啊" not in low_signal_texts
    assert "门都会带它很实用" not in low_signal_texts


def test_backend_subtitle_surface_helpers_split_semantic_and_spoken_contracts() -> None:
    item = {
        "text_final": "它算是定位相当高端的一款EDC手电了",
        "text_norm": "它算是定位相当高端的一款EDC手电了",
        "text_raw": "它算是定位相当高端的一款EC手电了",
        "transcript_text_raw": "它算是定位相当高端的一款EC手电了",
        "transcript_text": "它算是定位相当高端的一款EDC手电了",
    }

    assert subtitle_semantic_preview_text(item) == "它算是定位相当高端的一款EDC手电了"
    assert subtitle_spoken_rule_text(item) == "它算是定位相当高端的一款EC手电了"


def test_multimodal_trim_review_payload_selects_review_required_candidates() -> None:
    cut_analysis = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "其实也就这样吧"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "EDC17亮度一千五流明"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
        content_profile={
            "video_understanding": {
                "segment_understanding": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "role": "detail_showcase",
                        "keep_priority": "high",
                        "confidence": 0.88,
                    }
                ]
            }
        },
    )

    payload = build_multimodal_trim_review_payload(
        cut_analysis,
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    assert payload["schema"] == "multimodal_trim_review.v1"
    assert payload["candidate_count"] == 1
    assert payload["pending_count"] == 1
    assert payload["reviewed"] is False
    assert payload["candidates"][0]["reason"] == "low_signal_subtitle"
    assert payload["candidates"][0]["multimodal_keep_priority"] == "high"
    assert payload["candidates"][0]["multimodal_roles"] == ["detail_showcase"]
    assert payload["candidates"][0]["review_trigger"] == "visual_protection"


def test_multimodal_trim_review_payload_includes_low_signal_candidates_without_video_hints() -> None:
    cut_analysis = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "其实也就这样吧"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
    )

    payload = build_multimodal_trim_review_payload(
        cut_analysis,
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["reason"] == "low_signal_subtitle"
    assert payload["candidates"][0]["review_trigger"] == "semantic_uncertainty"


def test_multimodal_trim_review_payload_uses_registry_for_default_semantic_review_rules() -> None:
    payload = build_multimodal_trim_review_payload(
        {
            "rule_candidates": [
                {
                    "start": 1.0,
                    "end": 1.6,
                    "reason": "timing_trim",
                    "score": 0.74,
                }
            ]
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["reason"] == "timing_trim"
    assert payload["candidates"][0]["review_trigger"] == "semantic_uncertainty"


def test_extract_candidate_frame_times_uses_lighter_semantic_uncertainty_sampling() -> None:
    semantic_times = _extract_candidate_frame_times(
        10.0,
        12.0,
        candidate={"review_trigger": "semantic_uncertainty"},
    )
    visual_times = _extract_candidate_frame_times(
        10.0,
        12.0,
        candidate={"review_trigger": "visual_protection"},
    )

    assert len(semantic_times) == 1
    assert len(visual_times) == 3
    assert semantic_times[0] >= 0.0
    assert visual_times[-1] >= semantic_times[-1]


def test_multimodal_trim_review_timeout_scales_with_frame_budget() -> None:
    timeout = _resolve_multimodal_trim_review_timeout_seconds(
        SimpleNamespace(multimodal_trim_review_timeout_sec=20),
        candidate_count=3,
        image_count=3,
    )
    assert timeout == 48.0


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_resolves_short_textless_timing_trim_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"fake")
    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 1,
        "pending_count": 1,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
            {
                "candidate_id": "timing_trim:0.000:0.260:",
                "start": 0.0,
                "end": 0.26,
                "reason": "timing_trim",
                "source_text": None,
                "score": 0.65,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            }
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )

    async def fail_complete_with_images(*args, **kwargs) -> str:
        raise AssertionError("textless short timing_trim should not call the vision model")

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.complete_with_images", fail_complete_with_images)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=source_path,
        source_meta={"source_name": "demo.mp4"},
    )

    assert reviewed["reviewed"] is True
    assert reviewed["accepted_count"] == 1
    assert reviewed["pending_count"] == 0
    assert reviewed["candidates"][0]["review_state"] == "accepted"
    assert reviewed["decisions"][0]["source"] == "deterministic_boundary_trim"
    assert "provider" not in reviewed


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_resolves_failed_attempt_with_replacement_evidence_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"fake")
    source_text = "甩刀操作失败演示，说话人随即说明错误方式并在随后给出正确甩开的完整展示"
    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 1,
        "pending_count": 1,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
            {
                "candidate_id": f"failed_attempt:255.000:267.000:{source_text}",
                "start": 255.0,
                "end": 267.0,
                "reason": "failed_attempt",
                "source_text": source_text,
                "score": 0.85,
                "review_trigger": "visual_protection",
                "review_state": "pending",
            }
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )

    async def fail_complete_with_images(*args, **kwargs) -> str:
        raise AssertionError("text-confirmed failed_attempt should not call the vision model")

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.complete_with_images", fail_complete_with_images)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=source_path,
        source_meta={"source_name": "demo.mp4"},
    )

    assert reviewed["reviewed"] is True
    assert reviewed["accepted_count"] == 1
    assert reviewed["pending_count"] == 0
    assert reviewed["candidates"][0]["review_state"] == "accepted"
    assert reviewed["decisions"][0]["source"] == "deterministic_failed_attempt"
    assert "provider" not in reviewed


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_applies_model_verdicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"fake")
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")

    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 1,
        "pending_count": 1,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
            {
                "candidate_id": "low_signal_subtitle:0.000:0.900:然后呢",
                "start": 0.0,
                "end": 0.9,
                "reason": "low_signal_subtitle",
                "source_text": "然后呢",
                "score": 0.83,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            }
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.llm_task_route", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.track_usage_operation", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review._extract_candidate_preview_frames",
        lambda **kwargs: asyncio.sleep(0, result=[frame_path]),
    )

    async def fake_complete_with_images(prompt: str, image_paths: list[Path], **kwargs) -> str:
        assert image_paths == [frame_path]
        return '{"verdict":"keep","confidence":0.91,"reason":"画面仍在展示关键细节","evidence":["细节展示"],"summary":"应保留"}'

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.complete_with_images", fake_complete_with_images)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=source_path,
        source_meta={"source_name": "demo.mp4", "subject_model": "EDC17"},
    )

    assert reviewed["reviewed"] is True
    assert reviewed["rejected_count"] == 1
    assert reviewed["pending_count"] == 0
    assert reviewed["candidates"][0]["review_state"] == "rejected"
    assert reviewed["candidates"][0]["review"]["verdict"] == "keep"
    assert reviewed["provider"] == "openai"
    assert reviewed["model"] == "gpt-5.5"


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_tracks_unsure_without_marking_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"fake")
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")

    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 1,
        "pending_count": 1,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
                {
                    "candidate_id": "timing_trim:1.000:2.000:这个边界",
                    "start": 1.0,
                    "end": 2.0,
                    "reason": "timing_trim",
                    "source_text": "这个边界",
                    "score": 0.5,
                    "review_trigger": "semantic_uncertainty",
                    "review_state": "pending",
            }
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.llm_task_route", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.track_usage_operation", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review._extract_candidate_preview_frames",
        lambda **kwargs: asyncio.sleep(0, result=[frame_path]),
    )

    async def fake_complete_with_images(prompt: str, image_paths: list[Path], **kwargs) -> str:
        assert image_paths == [frame_path]
        return '{"verdict":"unsure","confidence":0.0,"reason":"证据不足","evidence":[],"summary":""}'

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.complete_with_images", fake_complete_with_images)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=source_path,
        source_meta={"source_name": "demo.mp4", "subject_model": "EDC17"},
    )

    assert reviewed["reviewed"] is True
    assert reviewed["pending_count"] == 0
    assert reviewed["unsure_count"] == 1
    assert reviewed["candidates"][0]["review_state"] == "unsure"


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_resolves_storage_path_when_direct_source_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    direct_source_path = tmp_path / "jobs" / "demo.mp4"
    resolved_source_path = tmp_path / "resolved" / "demo.mp4"
    resolved_source_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_source_path.write_bytes(b"fake")
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")

    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 1,
        "pending_count": 1,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
            {
                "candidate_id": "timing_trim:1.000:2.000:这个边界",
                "start": 1.0,
                "end": 2.0,
                "reason": "timing_trim",
                "source_text": "这个边界",
                "score": 0.66,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            }
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.llm_task_route", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.track_usage_operation", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_storage",
        lambda: SimpleNamespace(resolve_path=lambda key: resolved_source_path if str(key) == str(direct_source_path) else Path(key)),
    )
    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review._extract_candidate_preview_frames",
        lambda **kwargs: asyncio.sleep(0, result=[frame_path]),
    )

    async def fake_complete_with_images(prompt: str, image_paths: list[Path], **kwargs) -> str:
        assert image_paths == [frame_path]
        return '{"verdict":"cut","confidence":0.88,"reason":"只是节奏修剪","evidence":["边界"],"summary":"可删"}'

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.complete_with_images", fake_complete_with_images)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=direct_source_path,
        source_meta={"source_name": "demo.mp4", "subject_model": "EDC17"},
    )

    assert reviewed.get("error") is None
    assert reviewed["reviewed"] is True
    assert reviewed["accepted_count"] == 1
    assert reviewed["pending_count"] == 0


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_batches_uncached_candidates_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"fake")
    frame_a = tmp_path / "frame-a.jpg"
    frame_b = tmp_path / "frame-b.jpg"
    frame_c = tmp_path / "frame-c.jpg"
    frame_d = tmp_path / "frame-d.jpg"
    for frame in (frame_a, frame_b, frame_c, frame_d):
        frame.write_bytes(b"frame")

    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 2,
        "pending_count": 2,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
            {
                "candidate_id": "low_signal_subtitle:0.000:0.900:然后呢",
                "start": 0.0,
                "end": 0.9,
                "reason": "low_signal_subtitle",
                "source_text": "然后呢",
                "score": 0.83,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            },
            {
                "candidate_id": "timing_trim:1.000:2.000:这个边界",
                "start": 1.0,
                "end": 2.0,
                "reason": "timing_trim",
                "source_text": "这个边界",
                "score": 0.66,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            },
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.llm_task_route", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.track_usage_operation", lambda *args, **kwargs: nullcontext())

    async def fake_extract_candidate_preview_frames(**kwargs):
        source_text = str((kwargs.get("candidate") or {}).get("source_text") or "")
        return [frame_a, frame_b] if source_text == "然后呢" else [frame_c, frame_d]

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review._extract_candidate_preview_frames",
        fake_extract_candidate_preview_frames,
    )
    multimodal_calls: list[list[Path]] = []

    async def fake_complete_with_images(prompt: str, image_paths: list[Path], **kwargs) -> str:
        multimodal_calls.append(list(image_paths))
        return (
            '{"decisions":['
            '{"candidate_id":"low_signal_subtitle:0.000:0.900:然后呢","verdict":"keep","confidence":0.91,"reason":"仍在展示","evidence":["细节"],"summary":"保留"},'
            '{"candidate_id":"timing_trim:1.000:2.000:这个边界","verdict":"cut","confidence":0.88,"reason":"只是节奏修剪","evidence":["边界"],"summary":"可删"}'
            '],"summary":"批量复核完成"}'
        )

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.complete_with_images", fake_complete_with_images)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=source_path,
        source_meta={"source_name": "demo.mp4", "subject_model": "EDC17"},
    )

    assert len(multimodal_calls) == 1
    assert multimodal_calls[0] == [frame_a, frame_b, frame_c, frame_d]
    assert reviewed["reviewed"] is True
    assert reviewed["accepted_count"] == 1
    assert reviewed["rejected_count"] == 1
    assert reviewed["pending_count"] == 0


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_skips_frame_missing_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"fake")
    frame_path = tmp_path / "frame.jpg"
    frame_path.write_bytes(b"frame")

    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 2,
        "pending_count": 2,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
            {
                "candidate_id": "low_signal_subtitle:0.000:0.900:然后呢",
                "start": 0.0,
                "end": 0.9,
                "reason": "low_signal_subtitle",
                "source_text": "然后呢",
                "score": 0.83,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            },
            {
                "candidate_id": "timing_trim:1.000:2.000:这个边界",
                "start": 1.0,
                "end": 2.0,
                "reason": "timing_trim",
                "source_text": "这个边界",
                "score": 0.66,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            },
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.llm_task_route", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.track_usage_operation", lambda *args, **kwargs: nullcontext())

    async def fake_extract_candidate_preview_frames(**kwargs):
        source_text = str((kwargs.get("candidate") or {}).get("source_text") or "")
        return [] if source_text == "然后呢" else [frame_path]

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review._extract_candidate_preview_frames",
        fake_extract_candidate_preview_frames,
    )
    multimodal_calls: list[list[Path]] = []

    async def fake_complete_with_images(prompt: str, image_paths: list[Path], **kwargs) -> str:
        multimodal_calls.append(list(image_paths))
        return (
            '{"decisions":['
            '{"candidate_id":"timing_trim:1.000:2.000:这个边界","verdict":"cut","confidence":0.88,"reason":"只是节奏修剪","evidence":["边界"],"summary":"可删"}'
            '],"summary":"批量复核完成"}'
        )

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review.complete_with_images", fake_complete_with_images)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=source_path,
        source_meta={"source_name": "demo.mp4", "subject_model": "EDC17"},
    )

    assert multimodal_calls == [[frame_path]]
    assert reviewed["reviewed"] is True
    assert reviewed["accepted_count"] == 1
    assert reviewed["pending_count"] == 1
    by_id = {item["candidate_id"]: item for item in reviewed["candidates"]}
    assert by_id["low_signal_subtitle:0.000:0.900:然后呢"]["review_state"] == "pending"
    assert by_id["timing_trim:1.000:2.000:这个边界"]["review_state"] == "accepted"
    assert "缺少预览帧 1 条" in str(reviewed.get("summary") or "")


@pytest.mark.asyncio
async def test_review_multimodal_trim_review_payload_splits_batches_after_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"fake")
    payload = {
        "schema": "multimodal_trim_review.v1",
        "source_name": "demo.mp4",
        "job_flow_mode": "auto",
        "reviewed": False,
        "candidate_count": 2,
        "pending_count": 2,
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": [
            {
                "candidate_id": "low_signal_subtitle:0.000:0.900:然后呢",
                "start": 0.0,
                "end": 0.9,
                "reason": "low_signal_subtitle",
                "source_text": "然后呢",
                "score": 0.83,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            },
            {
                "candidate_id": "timing_trim:1.000:2.000:这个边界",
                "start": 1.0,
                "end": 2.0,
                "reason": "timing_trim",
                "source_text": "这个边界",
                "score": 0.66,
                "review_trigger": "semantic_uncertainty",
                "review_state": "pending",
            },
        ],
    }

    monkeypatch.setattr(
        "roughcut.edit.multimodal_trim_review.get_settings",
        lambda: SimpleNamespace(
            multimodal_trim_review_enabled=True,
            multimodal_trim_review_max_candidates=4,
            multimodal_trim_review_timeout_sec=12,
            multimodal_trim_review_min_confidence=0.72,
            active_reasoning_provider="openai",
            active_vision_model="gpt-5.5",
            ffmpeg_timeout_sec=10,
        ),
    )
    call_sizes: list[int] = []

    async def fake_batch(**kwargs):
        candidates = list(kwargs.get("candidates") or [])
        call_sizes.append(len(candidates))
        if len(candidates) > 1:
            raise asyncio.TimeoutError()
        candidate_id = str(candidates[0].get("candidate_id") or "")
        verdict = "keep" if "low_signal_subtitle" in candidate_id else "cut"
        confidence = 0.91 if verdict == "keep" else 0.88
        return (
            [
                {
                    "candidate_id": candidate_id,
                    "verdict": verdict,
                    "confidence": confidence,
                    "reason": "split fallback verdict",
                    "evidence": [],
                    "summary": "done",
                }
            ],
            {"summary": "split fallback batch"},
        )

    monkeypatch.setattr("roughcut.edit.multimodal_trim_review._review_multimodal_candidate_batch", fake_batch)

    reviewed = await review_multimodal_trim_review_payload(
        payload,
        source_path=source_path,
        source_meta={"source_name": "demo.mp4", "subject_model": "EDC17"},
    )

    assert call_sizes == [2, 1, 1]
    assert reviewed["reviewed"] is True
    assert reviewed.get("error") is None
    assert len(reviewed["decisions"]) == 2
    assert reviewed["rejected_count"] == 1
    assert reviewed["accepted_count"] == 1
    assert reviewed["pending_count"] == 0


@pytest.mark.asyncio
async def test_load_manual_editor_multimodal_trim_review_payload_prefers_matching_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = SimpleNamespace(id=uuid4(), source_name="demo.mp4", job_flow_mode="auto")
    cut_analysis = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 1.1, "text_final": "其实也就这样吧"},
            {"start_time": 1.0, "end_time": 2.0, "text_final": "EDC17亮度一千五流明"},
        ],
        smart_cut_rules={"smartDeleteEnabled": True},
    )
    reviewed_artifact_payload = {
        **build_multimodal_trim_review_payload(cut_analysis, source_name="demo.mp4", job_flow_mode="auto"),
        "reviewed": True,
        "decisions": [{"candidate_id": "low_signal_subtitle:0.000:1.100:其实也就这样吧", "verdict": "keep", "confidence": 0.9}],
    }

    async def fake_load_latest_optional_artifact(*args, **kwargs):
        return SimpleNamespace(data_json=reviewed_artifact_payload)

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", fake_load_latest_optional_artifact)

    payload = await _load_manual_editor_multimodal_trim_review_payload(
        None,
        job=job,
        cut_analysis_payload=cut_analysis,
    )

    assert payload["reviewed"] is True
    assert payload["decisions"][0]["verdict"] == "keep"


def test_apply_multimodal_trim_review_to_cut_analysis_vetoes_keep_candidates() -> None:
    cut_analysis = {
        "schema": "cut_analysis.v1",
        "accepted_cuts": [],
        "rule_candidates": [
            {
                "start": 0.0,
                "end": 0.9,
                "reason": "low_signal_subtitle",
                "source_text": "然后呢",
                "score": 0.83,
            },
            {
                "start": 1.0,
                "end": 2.0,
                "reason": "timing_trim",
                "source_text": "这个边界",
                "score": 0.61,
            },
        ],
        "candidate_count": 2,
        "rule_candidate_count": 2,
        "auto_apply_candidate_count": 0,
        "manual_confirm_candidate_count": 2,
    }
    review_payload = {
        "schema": "multimodal_trim_review.v1",
        "reviewed": True,
        "decisions": [
            {
                "candidate_id": "low_signal_subtitle:0.000:0.900:然后呢",
                "verdict": "keep",
                "confidence": 0.91,
                "reason": "仍在展示有效画面",
            },
            {
                "candidate_id": "timing_trim:1.000:2.000:这个边界",
                "verdict": "cut",
                "confidence": 0.88,
                "reason": "只是节奏修剪",
                "evidence": ["边界过长"],
            },
        ],
    }

    result = apply_multimodal_trim_review_to_cut_analysis(cut_analysis, review_payload)

    assert result["candidate_count"] == 1
    assert result["rule_candidate_count"] == 1
    assert result["auto_apply_candidate_count"] == 0
    assert result["manual_confirm_candidate_count"] == 1
    assert result["candidate_risk_summary"] == {
        "total": {"low": 0, "medium": 1, "high": 0},
        "auto_apply": {"low": 0, "medium": 0, "high": 0},
        "manual_confirm": {"low": 0, "medium": 1, "high": 0},
    }
    assert result["rule_candidates"][0]["reason"] == "timing_trim"
    assert result["rule_candidates"][0]["multimodal_review"]["verdict"] == "cut"
    assert result["multimodal_trim_review_summary"]["vetoed_candidate_count"] == 1
    assert result["multimodal_trim_review_summary"]["accepted_count"] == 0
    assert result["multimodal_trim_review_summary"]["rejected_count"] == 0


def test_multimodal_trim_review_auto_cut_candidates_filter_high_confidence_cut_verdicts() -> None:
    cut_analysis = {
        "rule_candidates": [
            {
                "start": 1.0,
                "end": 2.0,
                "reason": "low_signal_subtitle",
                "multimodal_review": {"verdict": "cut", "confidence": 0.83},
            },
            {
                "start": 3.0,
                "end": 4.0,
                "reason": "timing_trim",
                "multimodal_review": {"verdict": "keep", "confidence": 0.91},
            },
            {
                "start": 5.0,
                "end": 6.0,
                "reason": "timing_trim",
                "multimodal_review": {"verdict": "cut", "confidence": 0.55},
            },
        ]
    }

    result = multimodal_trim_review_auto_cut_candidates(cut_analysis, min_confidence=0.72)

    assert result == [
        {
            "start": 1.0,
            "end": 2.0,
            "reason": "low_signal_subtitle",
            "multimodal_review": {"verdict": "cut", "confidence": 0.83},
        }
    ]


def test_manual_editor_rule_segments_surface_multimodal_trim_review_source() -> None:
    payload = {
        "accepted_cuts": [],
        "rule_candidates": [
            {
                "start": 1.0,
                "end": 2.0,
                "reason": "timing_trim",
                "source_text": "这个边界",
                "multimodal_review": {
                    "candidate_id": "timing_trim:1.000:2.000:这个边界",
                    "verdict": "cut",
                    "confidence": 0.88,
                    "reason": "只是节奏修剪",
                    "evidence": ["边界过长"],
                },
            }
        ],
    }

    segments = _manual_editor_rule_segments(payload)

    assert len(segments) == 1
    assert segments[0].source == "multimodal_trim_review"
    assert segments[0].confidence == 0.88
    assert segments[0].detail == "只是节奏修剪"


def test_manual_editor_smart_cut_rules_payload_defaults_when_missing() -> None:
    payload = _manual_editor_smart_cut_rules_payload(None)
    assert payload is not None
    assert payload["fillers"] == DEFAULT_SMART_CUT_FILLERS
    assert payload["catchphrases"] == DEFAULT_SMART_CUT_CATCHPHRASES
    assert payload["pauseThresholdSec"] == 0.8
    assert payload["fillerStandaloneEnabled"] is True
    assert payload["fillerSentenceHeadEnabled"] is False
    assert payload["fillerSentenceTailEnabled"] is False
    assert payload["catchphraseEnabled"] is False


def test_smart_cut_rules_payload_normalizes_legacy_and_expanded_default_fillers() -> None:
    payload = normalize_smart_cut_rules_payload({
        "fillers": "嗯,呃,额,啊,呀,呢,吧,嘛,哦,喔,哎,唉,诶,欸,呃呃,嗯嗯",
    })

    assert payload["fillers"] == DEFAULT_SMART_CUT_FILLERS
    assert payload["fillerStandaloneEnabled"] is True
    assert payload["fillerSentenceHeadEnabled"] is False
    assert payload["fillerSentenceTailEnabled"] is False


def test_smart_cut_rules_payload_normalizes_disabled_smart_delete_reasons() -> None:
    payload = normalize_smart_cut_rules_payload({
        "disabledSmartDeleteReasons": [
            "low_signal_subtitle",
            "unknown_reason",
            "restart_retake",
            "low_signal_subtitle",
        ],
    })

    assert payload["disabledSmartDeleteReasons"] == ["restart_retake", "low_signal_subtitle"]


def test_smart_cut_rules_payload_preserves_previous_narrow_defaults() -> None:
    payload = normalize_smart_cut_rules_payload({
        "fillerEnabled": True,
        "fillerStandaloneEnabled": True,
        "fillerSentenceHeadEnabled": False,
        "fillerSentenceTailEnabled": False,
        "catchphraseEnabled": False,
        "repeatedEnabled": True,
        "pauseEnabled": True,
        "smartDeleteEnabled": True,
        "pauseThresholdSec": 0.8,
        "fillers": DEFAULT_SMART_CUT_FILLERS,
        "catchphrases": DEFAULT_SMART_CUT_CATCHPHRASES,
    })

    assert payload["fillerSentenceHeadEnabled"] is False
    assert payload["fillerSentenceTailEnabled"] is False
    assert payload["catchphraseEnabled"] is False


def test_smart_cut_rules_payload_preserves_previous_legacy_default_shape() -> None:
    payload = normalize_smart_cut_rules_payload({
        "fillerEnabled": True,
        "fillerStandaloneEnabled": True,
        "fillerContinuousEnabled": False,
        "catchphraseEnabled": False,
        "repeatedEnabled": True,
        "pauseEnabled": True,
        "smartDeleteEnabled": True,
        "pauseThresholdSec": 0.8,
        "fillers": DEFAULT_SMART_CUT_FILLERS,
        "catchphrases": DEFAULT_SMART_CUT_CATCHPHRASES,
    })

    assert payload["fillerSentenceHeadEnabled"] is False
    assert payload["fillerSentenceTailEnabled"] is False
    assert payload["catchphraseEnabled"] is False


def test_smart_cut_rules_payload_preserves_previous_expanded_head_only_default() -> None:
    payload = normalize_smart_cut_rules_payload({
        "fillerEnabled": True,
        "fillerStandaloneEnabled": True,
        "fillerSentenceHeadEnabled": True,
        "fillerSentenceTailEnabled": False,
        "catchphraseEnabled": False,
        "repeatedEnabled": True,
        "pauseEnabled": True,
        "smartDeleteEnabled": True,
        "pauseThresholdSec": 0.8,
        "fillers": DEFAULT_SMART_CUT_FILLERS,
        "catchphrases": DEFAULT_SMART_CUT_CATCHPHRASES,
    })

    assert payload["fillerStandaloneEnabled"] is True
    assert payload["fillerSentenceHeadEnabled"] is True
    assert payload["fillerSentenceTailEnabled"] is False
    assert payload["catchphraseEnabled"] is False


def test_smart_cut_rules_payload_preserves_previous_expanded_default_with_catchphrases() -> None:
    payload = normalize_smart_cut_rules_payload({
        "fillerEnabled": True,
        "fillerStandaloneEnabled": True,
        "fillerSentenceHeadEnabled": True,
        "fillerSentenceTailEnabled": False,
        "catchphraseEnabled": True,
        "repeatedEnabled": True,
        "pauseEnabled": True,
        "smartDeleteEnabled": True,
        "pauseThresholdSec": 0.8,
        "fillers": DEFAULT_SMART_CUT_FILLERS,
        "catchphrases": DEFAULT_SMART_CUT_CATCHPHRASES,
    })

    assert payload["fillerStandaloneEnabled"] is True
    assert payload["fillerSentenceHeadEnabled"] is True
    assert payload["fillerSentenceTailEnabled"] is False
    assert payload["catchphraseEnabled"] is True


def test_refine_decision_plan_payload_summarizes_cut_analysis_candidates() -> None:
    cut_analysis = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [{"start": 1.0, "end": 2.0, "reason": "silence", "auto_applied": True}],
            "manual_editor_rule_candidates": [
                {
                    "start": 3.0,
                    "end": 3.4,
                    "reason": "filler_word",
                    "candidate_stage": "manual_editor_full_transcript",
                    "auto_applied": False,
                }
            ],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 8.0}],
        source_duration_sec=8.0,
        mode="auto_refine",
        subtitle_fingerprint="abc",
        render_plan_version=3,
        cut_analysis=cut_analysis,
        audio_defaults={"target_lufs": -16.0},
        video_transform={"rotation_cw": 0},
        smart_cut_rules={"fillerEnabled": True, "pauseThresholdSec": 0.8},
    )

    assert payload["schema"] == "refine_decision_plan.v1"
    assert payload["candidate_summary"] == {
        "total": 2,
        "auto_apply": 2,
        "manual_confirm": 0,
        "rule_auto_apply": 1,
        "multimodal_auto_apply": 0,
        "analysis_schema": "cut_analysis.v1",
        "risk_levels": {
            "total": {"low": 2, "medium": 0, "high": 0},
            "auto_apply": {"low": 2, "medium": 0, "high": 0},
            "manual_confirm": {"low": 0, "medium": 0, "high": 0},
        },
    }
    assert payload["strategy_type"] == "information_density"
    assert payload["strategy_profile"] == build_strategy_profile_payload()
    assert payload["keep_segments"] == [
        {"start": 0.0, "end": 1.0},
        {"start": 2.0, "end": 8.0},
    ]
    assert payload["smart_cut_rules"]["fillerEnabled"] is True
    assert payload["smart_cut_rules"]["pauseThresholdSec"] == 0.8
    assert payload["smart_cut_rules"]["fillers"] == DEFAULT_SMART_CUT_FILLERS
    assert payload["smart_cut_rules"]["catchphrases"] == DEFAULT_SMART_CUT_CATCHPHRASES


def test_refine_decision_plan_auto_refine_applies_high_confidence_multimodal_cuts() -> None:
    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 10.0}],
        source_duration_sec=10.0,
        mode="auto_refine",
        cut_analysis={
            "schema": "cut_analysis.v1",
            "candidate_count": 1,
            "auto_apply_candidate_count": 0,
            "manual_confirm_candidate_count": 1,
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "low_signal_subtitle",
                    "multimodal_review": {"verdict": "cut", "confidence": 0.88},
                }
            ],
            "multimodal_trim_review_summary": {"accepted_count": 1, "pending_count": 0},
        },
    )

    assert payload["keep_segments"] == [{"start": 0.0, "end": 2.0}, {"start": 4.0, "end": 10.0}]
    assert payload["candidate_summary"]["rule_auto_apply"] == 0
    assert payload["candidate_summary"]["multimodal_auto_apply"] == 1
    assert payload["multimodal_auto_apply_cut_count"] == 1
    assert payload["multimodal_trim_review_summary"] == {"accepted_count": 1, "pending_count": 0}


def test_refine_decision_plan_auto_refine_applies_low_risk_rule_candidates() -> None:
    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 10.0}],
        source_duration_sec=10.0,
        mode="auto_refine",
        cut_analysis={
            "schema": "cut_analysis.v1",
            "candidate_count": 1,
            "auto_apply_candidate_count": 1,
            "manual_confirm_candidate_count": 0,
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "filler_word",
                    "risk_level": "low",
                    "auto_applied": True,
                }
            ],
        },
    )

    assert payload["keep_segments"] == [{"start": 0.0, "end": 2.0}, {"start": 4.0, "end": 10.0}]
    assert payload["candidate_summary"]["rule_auto_apply"] == 1
    assert payload["rule_auto_apply_cut_count"] == 1


def test_refine_decision_plan_modern_empty_accepted_cuts_keeps_rule_candidates_as_suggestions() -> None:
    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 10.0}],
        source_duration_sec=10.0,
        mode="auto_refine",
        cut_analysis={
            "schema": "cut_analysis.v1",
            "accepted_cuts": [],
            "accepted_cut_count": 0,
            "candidate_count": 1,
            "auto_apply_candidate_count": 1,
            "manual_confirm_candidate_count": 0,
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "silence",
                    "risk_level": "low",
                    "auto_applied": True,
                }
            ],
        },
    )

    assert payload["keep_segments"] == [{"start": 0.0, "end": 10.0}]
    assert payload["candidate_summary"]["auto_apply"] == 1
    assert payload["candidate_summary"]["rule_auto_apply"] == 0
    assert payload["rule_auto_apply_cut_count"] == 0


def test_refine_decision_plan_modern_empty_accepted_cuts_blocks_multimodal_candidate_auto_cut() -> None:
    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 10.0}],
        source_duration_sec=10.0,
        mode="auto_refine",
        cut_analysis={
            "schema": "cut_analysis.v1",
            "accepted_cuts": [],
            "accepted_cut_count": 0,
            "candidate_count": 1,
            "auto_apply_candidate_count": 0,
            "manual_confirm_candidate_count": 1,
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "low_signal_subtitle",
                    "multimodal_review": {"verdict": "cut", "confidence": 0.88},
                }
            ],
            "multimodal_trim_review_summary": {"accepted_count": 1, "pending_count": 0},
        },
    )

    assert payload["keep_segments"] == [{"start": 0.0, "end": 10.0}]
    assert payload["candidate_summary"]["multimodal_auto_apply"] == 0
    assert payload["multimodal_auto_apply_cut_count"] == 0


def test_refine_decision_plan_auto_refine_resolves_legacy_low_risk_rule_candidates() -> None:
    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 10.0}],
        source_duration_sec=10.0,
        mode="auto_refine",
        cut_analysis={
            "schema": "cut_analysis.v1",
            "job_flow_mode": "auto",
            "candidate_count": 1,
            "auto_apply_candidate_count": 1,
            "manual_confirm_candidate_count": 0,
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "filler_word",
                }
            ],
        },
    )

    assert payload["keep_segments"] == [{"start": 0.0, "end": 2.0}, {"start": 4.0, "end": 10.0}]
    assert payload["candidate_summary"]["rule_auto_apply"] == 1
    assert payload["rule_auto_apply_cut_count"] == 1


def test_refine_decision_plan_manual_refine_keeps_auto_applied_rule_candidates_as_suggestions_only() -> None:
    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 10.0}],
        source_duration_sec=10.0,
        mode="manual_refine",
        cut_analysis={
            "schema": "cut_analysis.v1",
            "candidate_count": 1,
            "auto_apply_candidate_count": 1,
            "manual_confirm_candidate_count": 0,
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "filler_word",
                    "risk_level": "low",
                    "auto_applied": True,
                }
            ],
        },
    )

    assert payload["keep_segments"] == [{"start": 0.0, "end": 10.0}]
    assert payload["candidate_summary"]["rule_auto_apply"] == 0
    assert payload["rule_auto_apply_cut_count"] == 0


def test_refine_decision_plan_manual_refine_keeps_multimodal_cuts_as_suggestions_only() -> None:
    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 10.0}],
        source_duration_sec=10.0,
        mode="manual_refine",
        cut_analysis={
            "schema": "cut_analysis.v1",
            "candidate_count": 1,
            "auto_apply_candidate_count": 0,
            "manual_confirm_candidate_count": 1,
            "rule_candidates": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "low_signal_subtitle",
                    "multimodal_review": {"verdict": "cut", "confidence": 0.88},
                }
            ],
        },
    )

    assert payload["keep_segments"] == [{"start": 0.0, "end": 10.0}]
    assert payload["candidate_summary"]["multimodal_auto_apply"] == 0


def test_refine_plan_audio_defaults_merge_loudness_and_voice_processing() -> None:
    assert refine_plan_audio_defaults(
        {
            "loudness": {"target_lufs": -16.0, "peak_limit": -2.0},
            "voice_processing": {"noise_reduction": True},
        }
    ) == {
        "target_lufs": -16.0,
        "peak_limit": -2.0,
        "noise_reduction": True,
    }


def test_refine_decision_plan_from_render_plan_reuses_shared_defaults() -> None:
    cut_analysis = build_cut_analysis_payload(
        editorial_analysis={
            "accepted_cuts": [{"start": 1.0, "end": 2.0, "reason": "silence", "auto_applied": True}],
        },
        source_name="demo.mp4",
        job_flow_mode="auto",
    )

    payload = build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 0.0, "end": 8.0}],
        source_duration_sec=8.0,
        mode="manual_refine",
        subtitle_fingerprint="abc",
        render_plan_data={
            "loudness": {"target_lufs": -16.0},
            "voice_processing": {"noise_reduction": True},
        },
        render_plan_version=5,
        cut_analysis=cut_analysis,
        video_transform={"rotation_cw": 90},
        note="review",
    )

    assert payload["audio_defaults"] == {"target_lufs": -16.0, "noise_reduction": True}
    assert payload["video_transform"] == {"rotation_cw": 90}
    assert payload["candidate_summary"]["total"] == 1
    assert payload["render_plan_version"] == 5


def test_refine_decision_plan_from_render_plan_reuses_passed_audio_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from roughcut.edit import refine_decisions as refine_decisions_module

    monkeypatch.setattr(
        refine_decisions_module,
        "refine_plan_audio_defaults",
        lambda _payload: (_ for _ in ()).throw(AssertionError("should reuse passed audio defaults")),
    )

    payload = build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 0.0, "end": 8.0}],
        source_duration_sec=8.0,
        mode="manual_refine",
        render_plan_data={"loudness": {"target_lufs": -18.0}},
        audio_defaults={"target_lufs": -16.0, "noise_reduction": True},
        cut_analysis={},
        video_transform={"rotation_cw": 90},
    )

    assert payload["audio_defaults"] == {"target_lufs": -16.0, "noise_reduction": True}
    assert payload["video_transform"] == {"rotation_cw": 90}


def test_refine_decision_plan_payload_inherits_strategy_profile_from_cut_analysis() -> None:
    cut_analysis = build_cut_analysis_payload(
        editorial_analysis={"strategy_type": "step_demonstration"},
        source_name="demo.mp4",
        job_flow_mode="auto",
        strategy_profile={"strategy_type": "step_demonstration", "speech_priority": "medium"},
    )

    payload = build_refine_decision_plan_payload(
        keep_segments=[{"start": 0.0, "end": 8.0}],
        source_duration_sec=8.0,
        mode="auto_refine",
        cut_analysis=cut_analysis,
    )

    assert payload["strategy_type"] == "step_demonstration"
    assert payload["strategy_profile"]["strategy_type"] == "step_demonstration"
    assert payload["strategy_profile"]["speech_priority"] == "medium"


def test_strategy_profile_payload_helpers_default_legacy_payloads_to_information_density() -> None:
    assert payload_strategy_type({}) == "information_density"
    assert payload_strategy_profile({}) == build_strategy_profile_payload()
    assert build_strategy_profile_payload()["schema"] == STRATEGY_PROFILE_SCHEMA_VERSION


def test_manual_editor_refine_decision_plan_payload_backfills_strategy_metadata_from_cut_analysis() -> None:
    payload = jobs_module._manual_editor_refine_decision_plan_payload(
        {
            "schema": "refine_decision_plan.v1",
            "mode": "manual_refine",
            "keep_segments": [{"start": 0.0, "end": 2.0}],
        },
        keep_segments=[{"start": 0.0, "end": 2.0}],
        source_duration_sec=2.0,
        subtitle_fingerprint="fp",
        render_plan_version=1,
        cut_analysis={
            "strategy_type": "step_demonstration",
            "strategy_profile": {"strategy_type": "step_demonstration", "speech_priority": "medium"},
        },
        audio_defaults={},
        video_transform={},
        smart_cut_rules=None,
        mode="manual_refine",
    )

    assert payload["strategy_type"] == "step_demonstration"
    assert payload["strategy_profile"]["strategy_type"] == "step_demonstration"
    assert payload["strategy_profile"]["speech_priority"] == "medium"


def test_refine_decision_plan_from_render_plan_defaults_smart_cut_rules() -> None:
    payload = build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 0.0, "end": 8.0}],
        source_duration_sec=8.0,
        mode="auto_refine",
        subtitle_fingerprint="abc",
        render_plan_data={},
        render_plan_version=2,
        cut_analysis={},
        video_transform={},
        smart_cut_rules=None,
    )

    assert payload["smart_cut_rules"]["fillers"] == DEFAULT_SMART_CUT_FILLERS
    assert payload["smart_cut_rules"]["catchphrases"] == DEFAULT_SMART_CUT_CATCHPHRASES


def test_resolve_refine_keep_segments_for_timeline_prefers_matching_bound_plan() -> None:
    payload = build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 1.0, "end": 3.0}],
        source_duration_sec=8.0,
        mode="auto_refine",
        subtitle_fingerprint="abc",
        render_plan_data={},
        render_plan_version=2,
        cut_analysis={},
        video_transform={},
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=4,
    )

    assert resolve_refine_keep_segments_for_timeline(
        payload,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=4,
        fallback_segments=[
            {"type": "keep", "start": 0.0, "end": 2.0},
            {"type": "remove", "start": 2.0, "end": 3.0},
        ],
    ) == [{"start": 1.0, "end": 3.0}]


def test_resolve_keep_segments_from_refine_plan_prefers_matching_timeline_bound_plan() -> None:
    payload = build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 1.0, "end": 3.0}],
        source_duration_sec=8.0,
        mode="auto_refine",
        subtitle_fingerprint="abc",
        render_plan_data={},
        render_plan_version=2,
        cut_analysis={},
        video_transform={},
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=4,
    )

    assert _resolve_keep_segments_from_refine_plan(
        payload,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=4,
        fallback_segments=[
            {"type": "keep", "start": 0.0, "end": 2.0},
            {"type": "remove", "start": 2.0, "end": 3.0},
        ],
    ) == [{"start": 1.0, "end": 3.0}]


def test_resolve_keep_segments_from_refine_plan_falls_back_when_timeline_binding_mismatches() -> None:
    payload = build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 1.0, "end": 3.0}],
        source_duration_sec=8.0,
        mode="auto_refine",
        subtitle_fingerprint="abc",
        render_plan_data={},
        render_plan_version=2,
        cut_analysis={},
        video_transform={},
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=4,
    )

    assert _resolve_keep_segments_from_refine_plan(
        payload,
        editorial_timeline_id="timeline-2",
        editorial_timeline_version=5,
        fallback_segments=[
            {"type": "keep", "start": 0.0, "end": 2.0},
            {"type": "remove", "start": 2.0, "end": 3.0},
        ],
    ) == [{"start": 0.0, "end": 2.0}]


def test_resolve_render_keep_segments_prefers_explicit_refine_segments() -> None:
    assert _resolve_render_keep_segments(
        {
            "segments": [
                {"start": 0.0, "end": 1.0, "type": "keep"},
                {"start": 1.0, "end": 2.0, "type": "remove"},
            ]
        },
        explicit_keep_segments=[{"start": 3.0, "end": 4.5}],
    ) == [{"start": 3.0, "end": 4.5}]


def test_resolve_render_keep_segments_falls_back_to_editorial_timeline() -> None:
    assert _resolve_render_keep_segments(
        {
            "segments": [
                {"start": 0.0, "end": 1.0, "type": "keep"},
                {"start": 1.0, "end": 2.0, "type": "remove"},
                {"start": 2.0, "end": 5.0, "type": "keep"},
            ]
        },
        explicit_keep_segments=None,
    ) == [{"start": 0.0, "end": 1.0}, {"start": 2.0, "end": 5.0}]


def test_manual_editor_base_keep_segment_dicts_prefers_refine_plan_segments() -> None:
    refine_payload = build_refine_decision_plan_from_render_plan(
        keep_segments=[{"start": 3.0, "end": 6.0}],
        source_duration_sec=10.0,
        mode="manual_refine",
        subtitle_fingerprint="abc",
        render_plan_data={},
        render_plan_version=3,
        cut_analysis={},
        video_transform={},
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=2,
    )

    assert _manual_editor_base_keep_segment_dicts(
        {"segments": [{"type": "keep", "start": 0.0, "end": 10.0}]},
        refine_plan_payload=refine_payload,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=2,
        source_duration_sec=10.0,
    ) == [{"start": 3.0, "end": 6.0}]


def test_manual_editor_base_keep_segment_dicts_falls_back_to_editorial_heal() -> None:
    assert _manual_editor_base_keep_segment_dicts(
        {
            "segments": [
                {"type": "keep", "start": 0.0, "end": 1.0},
                {"type": "keep", "start": 1.005, "end": 3.0},
            ]
        },
        refine_plan_payload=None,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=2,
        source_duration_sec=0.0,
    ) == [{"start": 0.0, "end": 3.0}]


def test_manual_editor_projection_baseline_prefers_latest_projected_subtitles() -> None:
    rows = _manual_editor_projection_baseline_rows(
        [
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.2,
                "text_final": "这是投影断句",
            }
        ],
        [
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 2.8,
                "text_final": "这是全文切分，不应该抢投影基线",
            }
        ],
    )

    assert rows == [
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.2,
            "text_final": "这是投影断句",
        }
    ]


def test_manual_editor_authoritative_projection_keeps_output_timeline_rows() -> None:
    rows = _manual_editor_authoritative_projection_items(
        projected_subtitles=[
            {
                "index": 8,
                "start_time": 24.7,
                "end_time": 27.073,
                "source_overlap_start_time": 26.3,
                "source_overlap_end_time": 28.673,
                "text_final": "没想到啊NOC现在这么火",
            }
        ],
        source_subtitles=[
            {
                "index": 8,
                "start_time": 26.3,
                "end_time": 28.673,
                "text_final": "没想到啊NOC现在这么火",
            }
        ],
        keep_segments=[
            {"start": 1.6, "end": 60.0},
        ],
    )

    assert rows[0]["start_time"] == 24.7
    assert rows[0]["end_time"] == 27.073
    assert rows[0]["source_overlap_start_time"] == 26.3
    assert rows[0]["source_overlap_end_time"] == 28.673


def test_manual_editor_projection_rows_as_source_rows_use_source_overlap_times() -> None:
    rows = _manual_editor_projection_rows_as_source_rows(
        [
            {
                "index": 8,
                "start_time": 24.7,
                "end_time": 27.073,
                "source_overlap_start_time": 26.3,
                "source_overlap_end_time": 28.673,
                "text_final": "没想到啊NOC现在这么火",
                "words": [{"word": "没", "start": 24.7, "end": 24.9}],
            }
        ],
        projection_data={"transcript_layer": "canonical_transcript"},
    )

    assert rows[0]["start_time"] == 26.3
    assert rows[0]["end_time"] == 28.673
    assert rows[0]["text_final"] == "没想到啊NOC现在这么火"
    assert rows[0]["words"] == []


def test_manual_editor_source_alignment_replaces_output_timeline_word_anchors() -> None:
    rows = _manual_editor_align_source_rows_to_asr_words(
        [
            {
                "index": 8,
                "start_time": 26.3,
                "end_time": 28.673,
                "text_final": "没想到啊NOC现在这么火",
                "projection_source": "canonical_transcript",
                "segmentation_locked": True,
            }
        ],
        [
            {"word": "没", "start": 26.3, "end": 26.38},
            {"word": "想", "start": 26.38, "end": 26.54},
            {"word": "到", "start": 26.54, "end": 26.7},
            {"word": "啊", "start": 26.7, "end": 26.94},
            {"word": "NOC", "start": 27.04, "end": 27.68},
            {"word": "现在", "start": 27.68, "end": 27.92},
            {"word": "这么", "start": 27.92, "end": 28.08},
            {"word": "火", "start": 28.08, "end": 28.24},
        ],
    )

    assert rows[0]["source_overlap_start_time"] == 26.3
    assert rows[0]["source_overlap_end_time"] == 28.24
    assert rows[0]["words"][0]["start"] == 26.3
    assert rows[0]["words"][-1]["end"] == 28.24


def test_manual_editor_subtitle_payload_accepts_projection_start_end_keys() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 7,
            "start": 99.26,
            "end": 101.18,
            "text_final": "但是这个确实是",
        },
        index=0,
    )

    assert payload.start_time == 99.26
    assert payload.end_time == 101.18
    assert payload.text_final == "但是这个确实是"


def test_manual_editor_subtitle_payload_preserves_source_index() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 65,
            "source_index": 52,
            "source_indexes": [52, 53],
            "start_time": 180.117,
            "end_time": 183.51,
            "text_final": "你长按它就是一个激光绿激光",
        },
        index=0,
    )

    assert payload.index == 65
    assert payload.source_index == 52
    assert payload.source_indexes == [52, 53]


def test_manual_editor_subtitle_payload_preserves_zero_index() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.0,
            "text_final": "第一句",
        },
        index=7,
    )

    assert payload.index == 0
    assert payload.source_index == 0


def test_manual_editor_projection_source_annotation_uses_output_mapping() -> None:
    annotated = _annotate_manual_projected_subtitle_sources(
        [
            {
                "index": 68,
                "start_time": 186.81,
                "end_time": 189.65,
                "text_final": "遛狗逗狗来说还是非常实用的一个功能啊",
            }
        ],
        [
            {"index": 52, "start_time": 188.807, "end_time": 192.22, "text_final": "你长按它就是一个激光绿激光"},
            {"index": 53, "start_time": 192.22, "end_time": 195.5, "text_final": "因为我家养狗六"},
            {"index": 54, "start_time": 195.5, "end_time": 198.36, "text_final": "遛狗逗狗来说还是非常实用的一个功能啊"},
        ],
        [
            {"start": 1.32, "end": 35.74},
            {"start": 38.46, "end": 121.5},
            {"start": 122.22, "end": 125.85},
            {"start": 126.66, "end": 152.1},
            {"start": 152.64, "end": 155.54},
            {"start": 157.12, "end": 175.84},
            {"start": 176.86, "end": 277.96},
        ],
    )

    assert annotated[0]["source_index"] == 54
    assert annotated[0]["source_indexes"][0] == 54


def test_manual_editor_split_source_fragments_get_unique_source_indexes() -> None:
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 0,
                "source_index": 0,
                "source_indexes": [0],
                "start_time": 0.0,
                "end_time": 18.0,
                "text_final": "今天终于收到了年前的最后的一款小玩具啊这个也是耗尽了我这次的欧气啊",
                "transcript_text": "今天终于收到了年前的最后的一款小玩具啊嗯这个也是耗尽了我这次的欧气啊",
            }
        ],
        reindex_fragments=True,
    )

    assert len(rows) > 1
    assert [row["source_index"] for row in rows] == [row["index"] for row in rows]
    assert len({row["source_index"] for row in rows}) == len(rows)
    assert all(row["transcript_text"] == row["text_final"] for row in rows)


def test_manual_editor_split_source_fragments_follow_word_timings() -> None:
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 0,
                "source_index": 0,
                "source_indexes": [0],
                "start_time": 1.6,
                "end_time": 15.747,
                "text_final": "哦今天终于收到了年前的最后的一款小玩具啊这个也是耗尽了我这次的欧",
                "words": [
                    {"word": "哦", "start": 1.6, "end": 2.08},
                    {"word": "今天", "start": 2.16, "end": 2.48},
                    {"word": "终于", "start": 2.96, "end": 3.44},
                    {"word": "收到了", "start": 3.44, "end": 4.16},
                    {"word": "年前的", "start": 4.48, "end": 5.28},
                    {"word": "最后的", "start": 6.24, "end": 6.72},
                    {"word": "一款", "start": 7.68, "end": 7.84},
                    {"word": "小玩具啊", "start": 8.0, "end": 8.56},
                    {"word": "这个也是", "start": 9.8, "end": 10.9},
                    {"word": "耗尽了", "start": 11.1, "end": 11.7},
                    {"word": "我这次的欧", "start": 12.0, "end": 13.4},
                ],
            }
        ],
        reindex_fragments=True,
    )

    assert len(rows) >= 2
    target = next(row for row in rows if "这个也是" in row["text_final"])
    assert target["start_time"] < 10.2
    assert target["end_time"] <= 13.5
    assert target["words"]


def test_manual_editor_split_source_fragments_keep_boundary_particles_with_previous_line() -> None:
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 0,
                "source_index": 0,
                "source_indexes": [0],
                "start_time": 1.36,
                "end_time": 12.0,
                "text_final": "啊，呃，今天我们直奔主题啊，呃，大家看到现在这个镜头里有两把手电啊，这个一把是EDC37",
            }
        ],
        reindex_fragments=True,
    )

    cleaned = _clean_manual_editor_subtitle_projection(
        rows,
        drop_empty=False,
        collapse_repeats=False,
        clean_text=True,
    )
    compact = "".join(str(row.get("text_final") or "").replace(" ", "") for row in cleaned)

    assert "今天我们直奔主题啊大家看到" in compact


def test_manual_editor_split_source_fragments_avoid_dangling_word_boundaries() -> None:
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 0,
                "source_index": 0,
                "source_indexes": [0],
                "start_time": 69.395,
                "end_time": 89.977,
                "text_final": "这个真的是难受能难受好久啊因为这款啊就是非常火爆非常热门的那个S零六的迷你款啊我们开枪吧",
            }
        ],
        reindex_fragments=True,
    )
    text_rows = [str(row.get("text_final") or "") for row in rows]

    assert not any(text.endswith("非") for text in text_rows)
    assert not any(text.endswith("非常") for text in text_rows)
    assert not any(text.endswith("S") for text in text_rows)
    assert not any(text.endswith("迷") for text in text_rows)
    assert "好久啊" in "".join(text_rows)
    assert "就是非常火爆" in "".join(text_rows)
    assert "S零六" in "".join(text_rows)
    assert "迷你款" in "".join(text_rows)


def test_manual_editor_split_source_fragments_do_not_emit_single_character_sentence_stubs() -> None:
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 0,
                "source_index": 0,
                "source_indexes": [0],
                "start_time": 24.08,
                "end_time": 31.44,
                "text_final": "直线上升没想到啊这NOC现在这么火这次也是啊",
                "words": [
                    {"word": "直线上升", "start": 24.08, "end": 26.96},
                    {"word": "没想到啊", "start": 26.96, "end": 27.2},
                    {"word": "这", "start": 27.2, "end": 27.28},
                    {"word": "NOC", "start": 27.28, "end": 27.6},
                    {"word": "现在这么火", "start": 27.6, "end": 30.48},
                    {"word": "这次也是啊", "start": 30.48, "end": 31.44},
                ],
            }
        ],
        reindex_fragments=True,
    )
    text_rows = [str(row.get("text_final") or "") for row in rows]

    assert len(rows) >= 2
    assert not any(text == "这" for text in text_rows)
    assert any("这NOC" in text or "NOC现在" in text for text in text_rows)


def test_manual_editor_revealed_asr_words_do_not_duplicate_adjacent_fragments() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 3,
                "start_time": 6.316,
                "end_time": 11.031,
                "text_final": "最后的一款小玩具啊",
            },
            {
                "index": 4,
                "start_time": 11.031,
                "end_time": 15.747,
                "text_final": "这个也是耗尽了我这次的欧",
            },
        ],
        [
            {"word": "最", "start": 6.4, "end": 6.5},
            {"word": "后的", "start": 6.5, "end": 7.0},
            {"word": "一款", "start": 7.0, "end": 8.0},
            {"word": "小玩具", "start": 8.0, "end": 9.4},
            {"word": "啊", "start": 9.4, "end": 9.6},
            {"word": "嗯", "start": 9.7, "end": 9.8},
            {"word": "这个也是", "start": 9.8, "end": 10.9},
            {"word": "耗尽", "start": 11.1, "end": 11.7},
        ],
    )

    assert rows[0]["transcript_text"] == "最后的一款小玩具啊嗯"
    assert rows[1]["transcript_text"] == "这个也是耗尽了我这次的欧"


def test_manual_editor_revealed_asr_words_trim_overlap_without_rewriting_row_boundary() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 177,
                "start_time": 858.0,
                "end_time": 859.0,
                "text_final": "合上以后",
            },
            {
                "index": 178,
                "start_time": 859.195,
                "end_time": 863.515,
                "text_final": "然后这个用手指弹开",
                "words": [
                    {"word": "然", "start": 859.195, "end": 859.355},
                    {"word": "后", "start": 859.355, "end": 859.515},
                    {"word": "这", "start": 859.515, "end": 859.675},
                    {"word": "个", "start": 859.675, "end": 859.835},
                    {"word": "嗯", "start": 862.155, "end": 863.515},
                ],
            }
        ],
        [
            {"word": "然", "start": 859.195, "end": 859.355},
            {"word": "后", "start": 859.355, "end": 859.515},
            {"word": "这", "start": 859.515, "end": 859.675},
            {"word": "个", "start": 859.675, "end": 859.835},
            {"word": "嗯", "start": 859.835, "end": 861.355},
            {"word": "用", "start": 861.355, "end": 861.435},
            {"word": "手", "start": 861.435, "end": 861.675},
            {"word": "指", "start": 861.675, "end": 861.835},
            {"word": "弹", "start": 861.835, "end": 861.995},
            {"word": "开", "start": 861.995, "end": 862.155},
        ],
    )

    assert rows[1]["start_time"] == 859.195
    assert rows[1]["end_time"] == 863.515
    assert rows[1]["source_overlap_start_time"] == 859.195
    assert rows[1]["source_overlap_end_time"] == 862.155
    assert "".join(word["word"] for word in rows[1]["words"]) == "然后这个用手指弹开"


def test_manual_editor_revealed_asr_words_do_not_replace_with_wrong_sentence() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 8,
                "start_time": 24.939,
                "end_time": 29.879,
                "text_final": "购难度直线上升 没想",
                "words": [
                    {"word": "购难度", "start": 24.939, "end": 26.174},
                    {"word": "直线上升", "start": 26.174, "end": 28.233},
                    {"word": "没想", "start": 28.233, "end": 29.879},
                ],
            },
            {
                "index": 9,
                "start_time": 29.879,
                "end_time": 34.819,
                "text_final": "到啊 NOC现在这么火",
            },
        ],
        [
            {"word": "呃", "start": 26.0, "end": 26.24},
            {"word": "没", "start": 26.32, "end": 26.4},
            {"word": "想", "start": 26.4, "end": 26.56},
            {"word": "到", "start": 26.56, "end": 26.72},
            {"word": "啊", "start": 26.72, "end": 26.96},
            {"word": "NOC", "start": 27.04, "end": 27.68},
            {"word": "现在", "start": 27.68, "end": 27.76},
            {"word": "这么火", "start": 27.76, "end": 28.24},
        ],
    )

    assert "transcript_text" not in rows[0]
    assert rows[0]["words"][0]["word"] == "购难度"


def test_manual_editor_source_alignment_preserves_existing_word_anchors() -> None:
    subtitles = [
        {
            "index": 12,
            "start_time": 58.24,
            "end_time": 61.12,
            "text_final": "节目的应该可以看出来啊",
            "words": [
                {"word": "节", "start": 58.24, "end": 58.48},
                {"word": "目", "start": 58.48, "end": 58.72},
                {"word": "的", "start": 58.72, "end": 58.96},
                {"word": "应", "start": 58.96, "end": 59.28},
                {"word": "该", "start": 59.28, "end": 59.6},
                {"word": "可", "start": 59.6, "end": 59.92},
                {"word": "以", "start": 59.92, "end": 60.24},
                {"word": "看", "start": 60.24, "end": 60.56},
                {"word": "出", "start": 60.56, "end": 60.8},
                {"word": "来", "start": 60.8, "end": 61.0},
                {"word": "啊", "start": 61.0, "end": 61.12},
            ],
        }
    ]
    raw_words = [
        *subtitles[0]["words"],
        {"word": "节", "start": 300.0, "end": 300.2},
        {"word": "目", "start": 300.2, "end": 300.4},
        {"word": "的", "start": 300.4, "end": 300.6},
        {"word": "应", "start": 300.6, "end": 300.8},
        {"word": "该", "start": 300.8, "end": 301.0},
        {"word": "可", "start": 301.0, "end": 301.2},
        {"word": "以", "start": 301.2, "end": 301.4},
        {"word": "看", "start": 301.4, "end": 301.6},
        {"word": "出", "start": 301.6, "end": 301.8},
        {"word": "来", "start": 301.8, "end": 302.0},
        {"word": "啊", "start": 302.0, "end": 302.2},
    ]

    rows = _manual_editor_align_source_rows_to_asr_words(subtitles, raw_words)

    assert rows[0]["start_time"] == 58.24
    assert rows[0]["end_time"] == 61.12
    assert "".join(word["word"] for word in rows[0]["words"]) == "节目的应该可以看出来啊"


def test_manual_editor_source_alignment_trims_overlap_without_rewriting_row_boundary() -> None:
    rows = _manual_editor_align_source_rows_to_asr_words(
        [
            {
                "index": 6,
                "start_time": 24.54,
                "end_time": 27.073,
                "text_final": "没想到",
                "words": [
                    {"word": "呃", "start": 26.06, "end": 26.3},
                    {"word": "没", "start": 26.3, "end": 26.38},
                    {"word": "想", "start": 26.38, "end": 26.54},
                    {"word": "到", "start": 26.54, "end": 26.7},
                    {"word": "啊", "start": 26.7, "end": 26.94},
                ],
            }
        ],
        [
            {"word": "呃", "start": 26.06, "end": 26.3},
            {"word": "没", "start": 26.3, "end": 26.38},
            {"word": "想", "start": 26.38, "end": 26.54},
            {"word": "到", "start": 26.54, "end": 26.7},
            {"word": "啊", "start": 26.7, "end": 26.94},
        ],
    )

    assert rows[0]["start_time"] == 24.54
    assert rows[0]["end_time"] == 27.073
    assert rows[0]["source_overlap_start_time"] == 26.3
    assert rows[0]["source_overlap_end_time"] == 26.7
    assert "".join(word["word"] for word in rows[0]["words"]) == "没想到"


def test_manual_editor_source_alignment_stays_within_local_time_window_for_unanchored_rows() -> None:
    rows = _manual_editor_align_source_rows_to_asr_words(
        [
            {
                "index": 12,
                "start_time": 58.24,
                "end_time": 61.12,
                "text_final": "节目的应该可以看出来啊",
            }
        ],
        [
            {"word": "节", "start": 58.24, "end": 58.48},
            {"word": "目", "start": 58.48, "end": 58.72},
            {"word": "的", "start": 58.72, "end": 58.96},
            {"word": "应", "start": 58.96, "end": 59.28},
            {"word": "该", "start": 59.28, "end": 59.6},
            {"word": "可", "start": 59.6, "end": 59.92},
            {"word": "以", "start": 59.92, "end": 60.24},
            {"word": "看", "start": 60.24, "end": 60.56},
            {"word": "出", "start": 60.56, "end": 60.8},
            {"word": "来", "start": 60.8, "end": 61.0},
            {"word": "啊", "start": 61.0, "end": 61.12},
            {"word": "节", "start": 300.0, "end": 300.2},
            {"word": "目", "start": 300.2, "end": 300.4},
            {"word": "的", "start": 300.4, "end": 300.6},
            {"word": "应", "start": 300.6, "end": 300.8},
            {"word": "该", "start": 300.8, "end": 301.0},
            {"word": "可", "start": 301.0, "end": 301.2},
            {"word": "以", "start": 301.2, "end": 301.4},
            {"word": "看", "start": 301.4, "end": 301.6},
            {"word": "出", "start": 301.6, "end": 301.8},
            {"word": "来", "start": 301.8, "end": 302.0},
            {"word": "啊", "start": 302.0, "end": 302.2},
        ],
    )

    assert rows[0]["start_time"] == 58.24
    assert rows[0]["end_time"] == 61.12
    assert rows[0]["source_overlap_start_time"] == 58.24
    assert rows[0]["source_overlap_end_time"] == 61.12
    assert "".join(word["word"] for word in rows[0]["words"]) == "节目的应该可以看出来啊"


def test_manual_editor_rejects_projection_text_mapped_to_wrong_source_phrase() -> None:
    assert _manual_projection_has_source_text_mismatch(
        [
            {
                "index": 72,
                "source_index": 41,
                "source_indexes": [41],
                "start_time": 102.2,
                "end_time": 104.0,
                "text_final": "那个NOC要出保卡了不对",
            }
        ],
        [
            {
                "index": 41,
                "start_time": 137.0,
                "end_time": 138.4,
                "text_final": "那身份卡啊",
            }
        ],
    )


def test_manual_editor_rejects_projection_that_drops_kept_source_words() -> None:
    assert _manual_projection_has_source_text_mismatch(
        [
            {
                "index": 1,
                "source_index": 2,
                "source_indexes": [2],
                "start_time": 10.0,
                "end_time": 14.8,
                "text_final": "也是耗尽了我这次的欧气啊靠",
            }
        ],
        [
            {
                "index": 2,
                "start_time": 11.0,
                "end_time": 15.7,
                "text_final": "这个也是耗尽了我这次的欧气啊靠",
            }
        ],
    )


def test_manual_editor_rejects_projection_single_row_single_char_truncation() -> None:
    assert _manual_projection_has_source_text_mismatch(
        [
            {
                "index": 1,
                "source_index": 2,
                "source_indexes": [2],
                "start_time": 10.0,
                "end_time": 14.8,
                "text_final": "ABCDXYZ",
            }
        ],
        [
            {
                "index": 2,
                "source_index": 2,
                "start_time": 11.0,
                "end_time": 15.7,
                "text_final": "ABCDXYZZ",
            }
        ],
    )


def test_manual_editor_rejects_projection_with_duplicate_noise_not_in_source() -> None:
    assert _manual_projection_has_source_text_mismatch(
        [
            {
                "index": 0,
                "source_index": 0,
                "source_indexes": [0],
                "start_time": 0.0,
                "end_time": 4.0,
                "text_final": "一把是EDC37是是之前我一直经常会用",
            },
            {
                "index": 1,
                "source_index": 1,
                "source_indexes": [1],
                "start_time": 4.0,
                "end_time": 8.0,
                "text_final": "那支电池池然后一根线",
            },
        ],
        [
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 4.0,
                "text_final": "一把是EDC37 是之前我一直经常会用",
            },
            {
                "index": 1,
                "start_time": 4.0,
                "end_time": 8.0,
                "text_final": "那支电池然后一根线",
            },
        ],
    )


def test_projection_validation_falls_back_to_source_remap_when_text_mapping_is_wrong() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 72,
                "source_index": 41,
                "source_indexes": [41],
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "那个NOC要出保卡了不对",
            }
        ],
        source_subtitles=[
            {
                "index": 41,
                "start_time": 101.0,
                "end_time": 102.0,
                "text_final": "那身份卡啊",
            }
        ],
        keep_segments=[{"start": 100.0, "end": 103.0}],
        fallback_source_subtitles=[
            {
                "index": 41,
                "start_time": 101.0,
                "end_time": 102.0,
                "text_final": "那身份卡啊",
            }
        ],
    )

    assert result.mismatch_detected is True
    assert result.fallback_used is True
    assert result.subtitles[0]["text_final"] == "那身份卡啊"
    assert result.subtitles[0]["start_time"] == 1.0
    assert result.subtitles[0]["source_index"] == 41


def test_projection_validation_fallback_keeps_display_subtitle_source_indexes() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 72,
                "source_index": 1,
                "source_indexes": [1],
                "start_time": 8.256,
                "end_time": 14.774,
                "text_final": "那个NOC要出保卡了不对",
            }
        ],
        source_subtitles=[
            {
                "index": 1,
                "source_index": 1,
                "source_indexes": [1],
                "start_time": 638.034,
                "end_time": 662.32,
                "text_final": "那身份卡啊",
                "projection_source": "canonical_transcript",
            }
        ],
        keep_segments=[{"start": 638.034, "end": 662.32}],
        fallback_source_subtitles=[
            {
                "index": 113,
                "source_index": 113,
                "source_indexes": [113],
                "start_time": 646.29,
                "end_time": 652.808,
                "text_final": "你的大拇指去戳也很顺手吧",
                "projection_source": "subtitle_item",
            }
        ],
    )

    assert result.mismatch_detected is True
    assert result.fallback_used is True
    assert result.subtitles[0]["text_final"] == "你的大拇指去戳也很顺手吧"
    assert result.subtitles[0]["source_index"] == 113
    assert result.subtitles[0]["source_indexes"] == [113]


def test_projection_validation_keeps_finer_projected_subtitle_when_text_is_subsequence() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 9,
                "source_index": 48,
                "source_indexes": [48],
                "start_time": 2.0,
                "end_time": 4.0,
                "text_final": "应该是完美的符合了我所有的这个EDC",
            }
        ],
        source_subtitles=[
            {
                "index": 48,
                "source_index": 48,
                "source_indexes": [48],
                "start_time": 157.6,
                "end_time": 162.56,
                "text_final": "应该是完美的符合了我所有的这个EDC手电的一个要求啊",
            }
        ],
        keep_segments=[{"start": 155.6, "end": 165.6}],
        fallback_source_subtitles=[
            {
                "index": 48,
                "source_index": 48,
                "source_indexes": [48],
                "start_time": 157.6,
                "end_time": 162.56,
                "text_final": "应该是完美的符合了我所有的这个EDC手电的一个要求啊",
            }
        ],
    )

    assert result.mismatch_detected is False
    assert result.fallback_used is False
    assert result.subtitles[0]["text_final"] == "应该是完美的符合了我所有的这个EDC"


def test_projection_validation_keeps_finer_projected_subtitle_when_source_row_has_bridge_prefix() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 10,
                "source_index": 42,
                "source_indexes": [42],
                "start_time": 3.0,
                "end_time": 5.0,
                "text_final": "我觉得EDC17啊其实还是更符合我自己需求吧",
            }
        ],
        source_subtitles=[
            {
                "index": 42,
                "source_index": 42,
                "source_indexes": [42],
                "start_time": 138.973,
                "end_time": 143.176,
                "text_final": "但是呢 我觉得EDC17啊其实还是更符合我自己需求吧",
            }
        ],
        keep_segments=[{"start": 138.0, "end": 144.0}],
        fallback_source_subtitles=[
            {
                "index": 42,
                "source_index": 42,
                "source_indexes": [42],
                "start_time": 138.973,
                "end_time": 143.176,
                "text_final": "但是呢 我觉得EDC17啊其实还是更符合我自己需求吧",
            }
        ],
    )

    assert result.mismatch_detected is False
    assert result.fallback_used is False
    assert result.subtitles[0]["text_final"] == "我觉得EDC17啊其实还是更符合我自己需求吧"


def test_projection_validation_keeps_short_tail_projection_fully_contained_in_long_source_row() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 11,
                "source_index": 48,
                "source_indexes": [48],
                "start_time": 3.0,
                "end_time": 4.2,
                "text_final": "�ֵ��һ��Ҫ��",
            }
        ],
        source_subtitles=[
            {
                "index": 48,
                "source_index": 48,
                "source_indexes": [48],
                "start_time": 157.6,
                "end_time": 162.56,
                "text_final": "Ӧ���������ķ����������е����EDC�ֵ��һ��Ҫ��",
            }
        ],
        keep_segments=[{"start": 155.6, "end": 165.6}],
        fallback_source_subtitles=[
            {
                "index": 48,
                "source_index": 48,
                "source_indexes": [48],
                "start_time": 157.6,
                "end_time": 162.56,
                "text_final": "Ӧ���������ķ����������е����EDC�ֵ��һ��Ҫ��",
            }
        ],
    )

    assert result.mismatch_detected is False
    assert result.fallback_used is False
    assert result.subtitles[0]["text_final"] == "�ֵ��һ��Ҫ��"


def test_projection_validation_repairs_protected_phrase_lost_inside_merged_projection() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 22,
                "source_index": 26,
                "source_indexes": [26, 24, 25],
                "start_time": 0.0,
                "end_time": 2.62,
                "text_final": "任何快递的快递都给你轻松干穿费力",
            }
        ],
        source_subtitles=[
            {"index": 24, "start_time": 77.46, "end_time": 78.5, "text_final": "任何快递的"},
            {"index": 25, "start_time": 78.5, "end_time": 79.28, "text_final": "快递都给你轻松干穿"},
            {
                "index": 26,
                "start_time": 79.28,
                "end_time": 81.92,
                "text_final": "毫不费力",
                "words": [
                    {"word": "毫", "start": 79.28, "end": 79.44},
                    {"word": "不", "start": 81.44, "end": 81.52},
                    {"word": "费", "start": 81.52, "end": 81.76},
                    {"word": "力", "start": 81.76, "end": 81.92},
                ],
            },
        ],
        keep_segments=[
            {"start": 77.46, "end": 79.52},
            {"start": 81.36, "end": 87.64},
        ],
        apply_annotation_repair=True,
    )

    assert [item["text_final"] for item in result.subtitles] == [
        "任何快递的",
        "快递都给你轻松干穿",
        "毫不费力",
    ]


def test_projection_validation_repairs_repeated_boundary_text_from_span_fallback() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 5,
                "source_index": 4,
                "source_indexes": [4, 3],
                "start_time": 0.0,
                "end_time": 1.18,
                "text_final": "太难太难了难上加难",
            }
        ],
        source_subtitles=[
            {
                "index": 3,
                "start_time": 17.12,
                "end_time": 20.0,
                "text_final": "NOC的这个发售太难了",
                "words": [
                    {"word": "NOC", "start": 17.12, "end": 17.52},
                    {"word": "的", "start": 17.52, "end": 17.6},
                    {"word": "这", "start": 17.6, "end": 17.76},
                    {"word": "个", "start": 17.76, "end": 18.32},
                    {"word": "发", "start": 18.4, "end": 18.56},
                    {"word": "售", "start": 18.56, "end": 18.72},
                    {"word": "啊", "start": 18.72, "end": 18.88},
                    {"word": "太", "start": 19.6, "end": 19.84},
                    {"word": "难", "start": 19.84, "end": 20.0},
                ],
            },
            {
                "index": 4,
                "start_time": 20.0,
                "end_time": 20.78,
                "text_final": "太难了难上加难",
                "words": [
                    {"word": "了", "start": 20.0, "end": 20.14},
                    {"word": "难", "start": 20.14, "end": 20.22},
                    {"word": "上", "start": 20.3, "end": 20.38},
                    {"word": "加", "start": 20.38, "end": 20.54},
                    {"word": "难", "start": 20.54, "end": 20.78},
                ],
            },
        ],
        keep_segments=[{"start": 19.6, "end": 20.78}],
        apply_annotation_repair=True,
    )

    assert [item["text_final"] for item in result.subtitles] == ["太难", "了难上加难"]
    assert "".join(item["text_final"] for item in result.subtitles) == "太难了难上加难"


def test_projection_validation_repairs_missing_text_from_span_fallback_without_phrase_list() -> None:
    result = validate_projected_subtitles_against_source(
        [
            {
                "index": 22,
                "source_index": 26,
                "source_indexes": [26, 24, 25],
                "start_time": 0.0,
                "end_time": 2.62,
                "text_final": "任何快递的快递都给你轻松干穿费力",
            }
        ],
        source_subtitles=[
            {"index": 24, "start_time": 77.46, "end_time": 78.5, "text_final": "任何快递的"},
            {"index": 25, "start_time": 78.5, "end_time": 79.28, "text_final": "快递都给你轻松干穿"},
            {
                "index": 26,
                "start_time": 79.28,
                "end_time": 81.92,
                "text_final": "完全省力",
                "words": [
                    {"word": "完", "start": 79.28, "end": 79.44},
                    {"word": "全", "start": 81.44, "end": 81.52},
                    {"word": "省", "start": 81.52, "end": 81.76},
                    {"word": "力", "start": 81.76, "end": 81.92},
                ],
            },
        ],
        keep_segments=[
            {"start": 77.46, "end": 79.52},
            {"start": 81.36, "end": 87.64},
        ],
        apply_annotation_repair=True,
    )

    assert [item["text_final"] for item in result.subtitles] == [
        "任何快递的",
        "快递都给你轻松干穿",
        "完全省力",
    ]


def test_transcript_projection_validation_blocks_kept_asr_speech_without_subtitle() -> None:
    result = validate_projected_subtitles_against_transcript(
        [
            {"start_time": 0.0, "end_time": 0.4, "text_final": "今天"},
        ],
        transcript_segments=[
            {
                "index": 0,
                "text": "今天看手电",
                "words": [
                    {"word": "今天", "start": 0.0, "end": 0.35, "alignment": {"source": "provider"}},
                    {"word": "手电", "start": 1.0, "end": 1.35, "alignment": {"source": "provider"}},
                ],
            }
        ],
        keep_segments=[{"start": 0.0, "end": 2.0}],
    )

    assert result["blocking"] is True
    assert result["issue_counts"]["kept_transcript_speech_missing_projected_subtitle"] == 1
    assert result["blocking_examples"][0]["text"] == "手电"


def test_manual_editor_projection_falls_back_when_kept_asr_is_missing() -> None:
    assert _manual_editor_projection_should_use_source_fallback(
        [
            {"start_time": 0.0, "end_time": 0.4, "text_final": "今天"},
        ],
        source_subtitles=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 2.0,
                "text_final": "今天看手电",
                "words": [
                    {"word": "今天", "start": 0.0, "end": 0.35, "alignment": {"source": "provider"}},
                    {"word": "手电", "start": 1.0, "end": 1.35, "alignment": {"source": "provider"}},
                ],
            }
        ],
        keep_segments=[{"start": 0.0, "end": 2.0}],
    ) is True


def test_manual_editor_projection_ignores_sparse_boundary_token_misses_in_large_projection() -> None:
    assert _manual_editor_transcript_projection_blocking_is_significant(
        {
            "blocking": True,
            "blocking_issue_count": 41,
            "kept_speech_unit_count": 2118,
            "blocking_examples": [
                {
                    "type": "speech_token",
                    "text": "我",
                    "duration_sec": 0.125,
                },
                {
                    "type": "speech_token",
                    "text": "们",
                    "duration_sec": 0.125,
                },
                {
                    "type": "speech_token",
                    "text": "但",
                    "duration_sec": 0.055,
                },
            ],
        }
    ) is False

    assert _manual_editor_transcript_projection_blocking_is_significant(
        {
            "blocking": True,
            "blocking_issue_count": 1,
            "kept_speech_unit_count": 2,
            "blocking_examples": [
                {
                    "type": "speech_token",
                    "text": "手电",
                    "duration_sec": 0.35,
                }
            ],
        }
    ) is True


def test_manual_editor_split_piece_timings_reject_sparse_cross_segment_matches() -> None:
    item = {
        "words": [
            {"word": char, "start": offset * 0.1, "end": (offset + 1) * 0.1}
            for offset, char in enumerate("开关啊去触发")
        ]
        + [
            {"word": char, "start": 10.0 + offset * 0.1, "end": 10.1 + offset * 0.1}
            for offset, char in enumerate("为什么我平时出门遛狗")
        ]
        + [
            {"word": char, "start": 30.0 + offset * 0.1, "end": 30.1 + offset * 0.1}
            for offset, char in enumerate("一个功能")
        ],
    }

    assert jobs_module._manual_editor_split_piece_timings_from_words(
        item,
        [
            {
                "text": "开关啊去触发一个功能",
                "start_time": 0.0,
                "end_time": 2.0,
            }
        ],
    ) == [None]


def test_manual_editor_projection_falls_back_on_duplicate_source_alternatives() -> None:
    projected = [
        {"index": 70, "source_index": 41, "source_indexes": [41], "start_time": 100.0, "end_time": 101.2, "text_final": "那身份牌啊"},
        {"index": 71, "source_index": 41, "source_indexes": [41], "start_time": 100.02, "end_time": 101.18, "text_final": "那身份卡啊"},
    ]

    assert _manual_editor_projected_subtitles_have_duplicate_source_overlap(projected) is True
    assert _manual_editor_projection_should_use_source_fallback(
        projected,
        source_subtitles=[
            {"index": 41, "start_time": 137.0, "end_time": 138.4, "text_final": "那身份卡啊"},
        ],
        keep_segments=[{"start": 137.0, "end": 138.4}],
    ) is True


def test_manual_editor_source_fallback_splits_long_subtitle_rows() -> None:
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 9,
                "source_index": 9,
                "source_indexes": [9],
                "start_time": 0.0,
                "end_time": 8.0,
                "text_final": "没有这个像很多兄弟一样隐恨总算这个年还能过不然这个真的是难受能难受好久",
            }
        ]
    )

    assert len(rows) > 1
    assert all(len(row["text_final"]) <= 32 for row in rows)
    assert "".join(row["text_final"] for row in rows) == "没有这个像很多兄弟一样隐恨总算这个年还能过不然这个真的是难受能难受好久"
    assert rows[0]["source_fragment_count"] == len(rows)


def test_manual_editor_source_fallback_projection_preserves_source_row_boundaries() -> None:
    projected = _manual_editor_source_fallback_projection_items(
        [
            {
                "index": 0,
                "start_time": 10.0,
                "end_time": 12.0,
                "text_final": "或者说简单的这个短途的通勤啊",
                "words": [{"word": char, "start": 10.0 + index * 0.1, "end": 10.05 + index * 0.1} for index, char in enumerate("或者说简单的这个短途的通勤啊")],
            },
            {
                "index": 1,
                "start_time": 12.0,
                "end_time": 14.0,
                "text_final": "晚上出门都会带它很实用",
                "words": [{"word": char, "start": 12.0 + index * 0.1, "end": 12.05 + index * 0.1} for index, char in enumerate("晚上出门都会带它很实用")],
            },
        ],
        [{"start": 10.0, "end": 14.0}],
    )

    assert [item["text_final"] for item in projected] == [
        "或者说简单的这个短途的通勤啊",
        "晚上出门都会带它很实用",
    ]


def test_manual_editor_split_long_rows_use_timing_text_as_segmentation_authority() -> None:
    final_text = "或者说简单的这个短途的通勤啊晚上出门都会带它很实用而且它的这个UV的功能啊"
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 8.0,
                "text_raw": "或者说简单的这个晚上出门都会带它很实用",
                "transcript_text": "或者说简单的这个晚上出门都会带它很实用",
                "text_final": final_text,
                "timing_text": final_text,
                "words": [
                    {"word": char, "start": index * 0.1, "end": index * 0.1 + 0.05}
                    for index, char in enumerate(final_text)
                ],
            }
        ]
    )

    assert "".join(row["text_final"] for row in rows) == final_text
    assert any("短途的通勤啊" in row["text_final"] for row in rows)


def test_transcript_projection_validation_ignores_speech_removed_by_cut() -> None:
    result = validate_projected_subtitles_against_transcript(
        [
            {"start_time": 0.0, "end_time": 0.35, "text_final": "今天"},
        ],
        transcript_segments=[
            {
                "index": 0,
                "text": "今天看手电",
                "words": [
                    {"word": "今天", "start": 0.0, "end": 0.35, "alignment": {"source": "provider"}},
                    {"word": "手电", "start": 1.0, "end": 1.35, "alignment": {"source": "provider"}},
                ],
            }
        ],
        keep_segments=[{"start": 0.0, "end": 0.5}],
    )

    assert result["blocking"] is False
    assert result["kept_speech_unit_count"] == 1
    assert result["covered_speech_unit_count"] == 1


def test_transcript_projection_validation_warns_for_synthetic_timing_gap() -> None:
    result = validate_projected_subtitles_against_transcript(
        [],
        transcript_segments=[
            {
                "index": 0,
                "text": "今天看手电",
                "words": [
                    {
                        "word": "手电",
                        "start": 1.0,
                        "end": 1.35,
                        "alignment": {"source": "roughcut_synthesized"},
                    },
                ],
            }
        ],
        keep_segments=[{"start": 0.0, "end": 2.0}],
    )

    assert result["blocking"] is False
    assert result["warning_issue_count"] == 1
    assert result["issue_counts"]["synthetic_timing_speech_missing_projected_subtitle"] == 1


def test_transcript_projection_validation_prefers_explicit_canonical_surface_for_text_only_segments() -> None:
    result = validate_projected_subtitles_against_transcript(
        [],
        transcript_segments=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "text": "generic text should not override canonical transcript",
                "text_raw": "你看到的是EC手电",
                "text_canonical": "你看到的是EDC手电",
            }
        ],
        keep_segments=[{"start": 0.0, "end": 1.0}],
    )

    assert result["blocking"] is True
    assert result["blocking_examples"][0]["text"] == "你看到的是EDC手电"


def test_manual_editor_subtitle_payload_exposes_alignment_diagnostics_and_tokens() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 3,
            "start_time": 17.12,
            "end_time": 20.0,
            "text_final": "NOC的这个发售太难了",
            "words": [
                {"word": "NOC", "start": 17.12, "end": 17.52},
                {"word": "的", "start": 17.52, "end": 17.6},
                {"word": "这", "start": 17.6, "end": 17.76},
                {"word": "个", "start": 17.76, "end": 18.32},
                {"word": "发", "start": 18.4, "end": 18.56},
                {"word": "售", "start": 18.56, "end": 18.72},
                {"word": "太", "start": 19.6, "end": 19.84},
                {"word": "难", "start": 19.84, "end": 20.0},
            ],
        },
        index=3,
    )

    assert "".join(token.text for token in payload.alignment_tokens) == "NOC的这个发售太难了"
    assert payload.alignment_diagnostics is not None
    assert "unmatched_text_suffix" in payload.alignment_diagnostics["issues"]


def test_manual_editor_fragment_boundary_alignment_noise_does_not_raise_suffix_warning() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 7,
            "source_fragment_index": 5,
            "source_fragment_count": 60,
            "start_time": 17.12,
            "end_time": 20.0,
            "text_final": "了难上加难导致这个抢",
            "words": [
                {"word": "了", "start": 17.12, "end": 17.28},
                {"word": "难", "start": 17.28, "end": 17.44},
                {"word": "上", "start": 17.44, "end": 17.6},
                {"word": "加", "start": 17.6, "end": 17.76},
                {"word": "难", "start": 17.76, "end": 17.92},
                {"word": "导", "start": 17.92, "end": 18.08},
                {"word": "致", "start": 18.08, "end": 18.24},
                {"word": "这", "start": 18.24, "end": 18.4},
                {"word": "个", "start": 18.4, "end": 18.56},
            ],
        },
        index=7,
    )

    assert payload.alignment_diagnostics is not None
    assert "unmatched_text_suffix" not in payload.alignment_diagnostics["issues"]
    assert payload.alignment_diagnostics["status"] == "ok"


def test_manual_editor_fragment_boundary_alignment_noise_does_not_raise_prefix_warning() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 9,
            "source_fragment_index": 3,
            "source_fragment_count": 12,
            "start_time": 20.0,
            "end_time": 22.0,
            "text_final": "到啊NOC现在这么火",
            "words": [
                {"word": "啊", "start": 20.0, "end": 20.16},
                {"word": "N", "start": 20.16, "end": 20.28},
                {"word": "O", "start": 20.28, "end": 20.4},
                {"word": "C", "start": 20.4, "end": 20.52},
                {"word": "现", "start": 20.52, "end": 20.68},
                {"word": "在", "start": 20.68, "end": 20.84},
                {"word": "这", "start": 20.84, "end": 21.0},
                {"word": "么", "start": 21.0, "end": 21.16},
                {"word": "火", "start": 21.16, "end": 21.32},
            ],
        },
        index=9,
    )

    assert payload.alignment_diagnostics is not None
    assert "unmatched_text_prefix" not in payload.alignment_diagnostics["issues"]
    assert payload.alignment_diagnostics["status"] == "ok"


def test_manual_editor_alignment_uses_normalized_word_timings_for_multi_char_words() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 2.14,
            "end_time": 3.76,
            "text_final": "今天我们直奔主题",
            "words": [
                {"word": "今天", "start": 2.37, "end": 2.6},
                {"word": "我们", "start": 2.83, "end": 3.06},
                {"word": "直", "start": 3.06, "end": 3.38},
                {"word": "奔", "start": 3.38, "end": 3.5},
                {"word": "主", "start": 3.5, "end": 3.6},
                {"word": "题", "start": 3.6, "end": 3.76},
            ],
        },
        index=0,
    )

    assert [word.word for word in payload.words] == list("今天我们直奔主题")
    assert [(word.word, word.start, word.end) for word in payload.words[:4]] == [
        ("今", 2.37, 2.485),
        ("天", 2.485, 2.6),
        ("我", 2.83, 2.945),
        ("们", 2.945, 3.06),
    ]
    assert [(token.text, token.start, token.end) for token in payload.alignment_tokens[:4]] == [
        ("今", 2.37, 2.485),
        ("天", 2.485, 2.6),
        ("我", 2.83, 2.945),
        ("们", 2.945, 3.06),
    ]
    assert payload.alignment_diagnostics is not None
    assert payload.alignment_diagnostics["word_text"] == "今天我们直奔主题"
    assert payload.alignment_diagnostics["word_unit_count"] == 8


def test_manual_editor_alignment_diagnostics_deduplicate_repeated_word_timing_rows() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 2.14,
            "end_time": 3.76,
            "text_final": "今天我们直奔主题",
            "words": [
                {"word": "今天", "start": 2.37, "end": 2.6},
                {"word": "今天", "start": 2.37, "end": 2.6},
                {"word": "我们", "start": 2.83, "end": 3.06},
                {"word": "我们", "start": 2.83, "end": 3.06},
                {"word": "直", "start": 3.06, "end": 3.38},
                {"word": "奔", "start": 3.38, "end": 3.5},
                {"word": "主", "start": 3.5, "end": 3.6},
                {"word": "题", "start": 3.6, "end": 3.76},
            ],
        },
        index=0,
    )

    assert payload.alignment_diagnostics is not None
    assert payload.alignment_diagnostics["word_text"] == "今天我们直奔主题"
    assert payload.alignment_diagnostics["word_unit_count"] == 8


def test_manual_editor_keeps_projection_text_when_it_matches_source_phrase() -> None:
    assert not _manual_projection_has_source_text_mismatch(
        [
            {
                "index": 72,
                "source_index": 41,
                "source_indexes": [41],
                "start_time": 102.2,
                "end_time": 104.0,
                "text_final": "那个身份卡啊",
            }
        ],
        [
            {
                "index": 41,
                "start_time": 137.0,
                "end_time": 138.4,
                "text_final": "那身份卡啊",
            }
        ],
    )


def test_variant_subtitle_event_preserves_source_mapping_metadata() -> None:
    event = _normalize_subtitle_event(
        {
            "index": 72,
            "projection_source": "canonical_transcript",
            "source_index": 41,
            "source_indexes": [41, 42],
            "source_overlap_start_time": 101.0,
            "source_overlap_end_time": 102.0,
            "start_time": 1.0,
            "end_time": 2.0,
            "text_final": "那身份卡啊",
        }
    )

    assert event is not None
    assert event["text"] == "那身份卡啊"
    assert event["projection_source"] == "canonical_transcript"
    assert event["source_index"] == 41
    assert event["source_indexes"] == [41, 42]
    assert event["source_overlap_start_time"] == 101.0


def test_variant_subtitle_event_respects_display_surface_contract() -> None:
    assert (
        _normalize_subtitle_event(
            {
                "index": 7,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "你看到的是EC手电",
                "text_norm": "你看到的是EDC手电",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        )
        is None
    )

    event = _normalize_subtitle_event(
        {
            "index": 8,
            "start_time": 2.0,
            "end_time": 3.0,
            "text": "generic display text should not override explicit display surface",
            "text_raw": "你看到的是EC手电",
            "text_norm": "你看到的是EDC手电",
            "text_final": "你看到的是 EDC 手电",
        }
    )

    assert event is not None
    assert event["text"] == "你看到的是 EDC 手电"


def test_manual_editor_subtitle_payload_strips_local_asr_tags() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.0,
            "text_final": "给它塞进去啊EnvironmentalSounds哎",
        },
        index=0,
    )
    noise_payload = _manual_editor_subtitle_payload(
        {
            "index": 1,
            "start_time": 1.0,
            "end_time": 2.0,
            "text_final": "Noise 好",
        },
        index=1,
    )

    assert payload.text_final == "给它塞进去啊，哎"
    assert noise_payload.text_final == "好"


def test_manual_editor_subtitle_payload_normalizes_editable_text_contract() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 2.0,
            "text_raw": "今今天天终终于于收收到到了了年年前前的的一个个款款",
            "text_final": "今今天天终终于于收收到到了了年年前前的的一个个款款",
            "words": [
                {"word": char, "start": index * 0.05, "end": (index + 1) * 0.05}
                for index, char in enumerate("今今天天终终于于收收到到了了年年前前的的一个个款款")
            ],
        },
        index=0,
    )

    assert payload.text_raw == "今天终于收到了年前的一个款"
    assert payload.text_final == "今天终于收到了年前的一个款"
    assert "".join(token.text for token in payload.alignment_tokens) == "今天终于收到了年前的一个款"


def test_manual_editor_subtitle_payload_normalizes_mixed_anchor_alignment_tokens() -> None:
    raw = "没想到这NOC现NOC现在这么火"
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 2.0,
            "text_raw": raw,
            "text_final": raw,
            "words": [
                {"word": char, "start": index * 0.05, "end": (index + 1) * 0.05}
                for index, char in enumerate(raw)
            ],
        },
        index=0,
    )

    assert payload.text_raw == "没想到这NOC现在这么火"
    assert "".join(token.text for token in payload.alignment_tokens) == "没想到这NOC现在这么火"


def test_manual_editor_normalizes_legacy_word_timing_noise_before_attach() -> None:
    raw = "今今天天终终于于收收到到了了年年前前的的一个个款款"
    words = [
        {"word": char, "start": index * 0.05, "end": (index + 1) * 0.05, "source": "provider"}
        for index, char in enumerate(raw)
    ]

    normalized = _manual_editor_normalize_word_payloads_for_text(
        words,
        "今天终于收到了年前的一个款",
    )

    assert "".join(word["word"] for word in normalized) == "今天终于收到了年前的一个款"
    assert all(word["source"] == "provider" for word in normalized)


def test_manual_editor_drops_collapsed_duplicate_word_timestamps() -> None:
    normalized = _manual_editor_normalize_word_payloads_for_text(
        [
            {"word": "这", "start": 10.0, "end": 10.001, "source": "provider"},
            {"word": "个", "start": 10.001, "end": 10.002, "source": "provider"},
            {"word": "开", "start": 10.002, "end": 10.003, "source": "provider"},
            {"word": "法", "start": 10.003, "end": 10.004, "source": "provider"},
            {"word": "很", "start": 10.004, "end": 10.005, "source": "provider"},
            {"word": "顺", "start": 10.005, "end": 10.006, "source": "provider"},
            {"word": "手", "start": 10.006, "end": 10.007, "source": "provider"},
            {"word": "啊", "start": 10.007, "end": 10.008, "source": "provider"},
        ],
        "这个开法很顺手啊",
    )

    assert normalized == []


def test_manual_editor_normalize_word_payloads_keeps_original_words_when_model_alias_adds_ascii_units() -> None:
    raw = "所以呢我的选择就是这个幺七"
    words = [
        {"word": char, "start": index * 0.1, "end": (index + 1) * 0.1, "source": "provider"}
        for index, char in enumerate(raw)
    ]

    normalized = _manual_editor_normalize_word_payloads_for_text(
        words,
        "所以呢我的选择就是这个EDC17",
    )

    assert "".join(word["word"] for word in normalized) == raw
    assert all(word["end"] - word["start"] >= 0.01 for word in normalized)


def test_manual_editor_normalize_word_payloads_keeps_original_words_when_numeric_text_adds_arabic_digits() -> None:
    raw = "两千五百流明"
    words = [
        {"word": char, "start": index * 0.1, "end": (index + 1) * 0.1, "source": "provider"}
        for index, char in enumerate(raw)
    ]

    normalized = _manual_editor_normalize_word_payloads_for_text(
        words,
        "2500流明",
    )

    assert "".join(word["word"] for word in normalized) == raw
    assert all(word["end"] - word["start"] >= 0.01 for word in normalized)


def test_manual_editor_subtitle_payload_reprojects_attached_words_to_canonical_text() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 2.0,
            "text_raw": "小玩具也是耗尽了我这次的欧气啊",
            "text_final": "小玩具也是耗尽了我这次的欧气啊",
            "words": [
                {"word": word, "start": index * 0.1, "end": (index + 1) * 0.1, "source": "provider"}
                for index, word in enumerate(["小玩具", "啊", "嗯", "这个", "也是", "耗尽了", "我", "这次", "的", "欧气", "啊", "我靠", "我"])
            ],
        },
        index=0,
    )

    assert "".join(word.word for word in payload.words) == "小玩具也是耗尽了我这次的欧气啊"


def test_manual_editor_subtitle_payload_does_not_fabricate_alignment_tokens_for_model_aliases() -> None:
    raw = "所以呢我的选择就是这个幺七"
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 3.0,
            "text_final": "所以呢我的选择就是这个EDC17",
            "words": [
                {"word": char, "start": index * 0.1, "end": (index + 1) * 0.1, "source": "provider"}
                for index, char in enumerate(raw)
            ],
        },
        index=0,
    )

    assert "".join(word.word for word in payload.words) == raw
    assert not any(token.text in {"E", "D", "C", "1"} for token in payload.alignment_tokens)
    assert all(token.end - token.start >= 0.01 for token in payload.alignment_tokens)


def test_manual_editor_split_long_rows_keep_segment_subtitle_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected_piece_timing_override(
        item: dict[str, object],
        pieces: list[dict[str, object]],
    ) -> list[tuple[float, float] | None]:
        raise AssertionError("word-segmented pieces should keep segment_subtitles timings")

    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_split_piece_timings_from_words",
        _unexpected_piece_timing_override,
    )

    def _char_words(text: str, start: float, step: float) -> list[dict[str, float | str]]:
        words: list[dict[str, float | str]] = []
        cursor = 0
        for char in text:
            if char.isspace():
                continue
            char_start = start + cursor * step
            words.append({"word": char, "start": char_start, "end": char_start + step})
            cursor += 1
        return words

    text = "开关啊去触发一个功能，要不然就是打开就碰运气了。或者说呢，你提前先调整好，这是很重要的。"
    item = {
        "index": 5,
        "start_time": 0.0,
        "end_time": 15.0,
        "text_final": text,
        "text_norm": text,
        "text_raw": text,
        "words": _char_words("开关啊去触发一个功能要不然就是打开就碰运气了", 0.0, 0.12)
        + _char_words("或者说呢你提前先调整好这是很重要的", 10.0, 0.12),
    }

    rows = _manual_editor_split_long_subtitle_rows([item])

    assert len(rows) >= 2
    assert rows[0]["start_time"] < 1.0
    assert rows[0]["end_time"] < 5.0
    assert rows[1]["start_time"] >= 9.0


def test_manual_editor_split_piece_coverage_detects_dropped_middle_clause() -> None:
    source_text = "所以说为什么我平时比如临时出个门遛个狗啊，啊，或者说简单的这个短途的通勤啊，这个晚上出门都会带它。呃，很实用，而且它的这个UV的功能啊，也不是说只限用照明"
    pieces = [
        {"text": "所以说为什么我平时比如临时出个门遛个狗啊，啊，"},
        {"text": "这个的啊，也不是说只限用照明"},
    ]

    assert not _manual_editor_split_pieces_cover_source_text(source_text, pieces)
    assert _manual_editor_split_pieces_cover_source_text(
        source_text,
        [{"text": source_text}],
    )


def test_manual_editor_split_long_rows_falls_back_when_segment_subtitles_drops_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = (
        "所以说为什么我平时比如临时出个门遛个狗啊，啊，"
        "或者说简单的这个短途的通勤啊，这个晚上出门都会带它。"
        "呃，很实用，而且它的这个UV的功能啊，也不是说只限用照明"
    )
    item = {
        "index": 15,
        "start_time": 432.28,
        "end_time": 446.12,
        "text_final": text,
        "text_norm": text,
        "text_raw": text,
        "words": [
            {"word": char, "start": 432.28 + index * 0.08, "end": 432.28 + (index + 1) * 0.08}
            for index, char in enumerate(text)
            if not char.isspace()
        ],
    }

    def _broken_segment_subtitles(*args: object, **kwargs: object) -> SimpleNamespace:
        entries = [
            SimpleNamespace(start=432.28, end=435.96, text_raw="所以说为什么我平时比如临时出个门遛个狗啊，啊，", text_norm="所以说为什么我平时比如临时出个门遛个狗啊。"),
            SimpleNamespace(start=439.64, end=446.12, text_raw="这个的啊，也不是说只限用照明", text_norm="这个的啊，也不是说只限用照明。"),
        ]
        return SimpleNamespace(entries=entries)

    monkeypatch.setattr(jobs_module, "segment_subtitles", _broken_segment_subtitles)

    rows = _manual_editor_split_long_subtitle_rows([item])

    rendered = "".join(str(row.get("text_final") or "") for row in rows)
    assert "短途的通勤" in rendered
    assert "晚上出门都会带它" in rendered
    assert "UV的功能" in rendered
    assert len(rows) > 2


def test_manual_editor_split_long_rows_expose_display_fallback_strategy_without_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "split_subtitle_display_item",
        lambda **_kwargs: [
            {"text": "第一段", "start_time": 10.0, "end_time": 13.0},
            {"text": "第二段", "start_time": 13.0, "end_time": 16.0},
        ],
    )

    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 2,
                "start_time": 10.0,
                "end_time": 16.0,
                "text_final": "第一段第二段",
            }
        ]
    )

    assert [row["text_final"] for row in rows] == ["第一段", "第二段"]
    assert rows[0]["split_strategy"] == "display_fallback_no_words"
    assert rows[0]["split_attempted"] is True
    assert rows[0]["source_fragment_count"] == 2
    assert rows[1]["split_strategy"] == "display_fallback_no_words"

    diagnostics = _manual_editor_source_row_split_diagnostics(rows)

    assert diagnostics["attempted_row_count"] == 1
    assert diagnostics["fragmented_row_count"] == 1
    assert diagnostics["fragment_count"] == 2
    assert diagnostics["strategy_counts"] == {"display_fallback_no_words": 1}


def test_manual_editor_split_long_rows_expose_word_timed_strategy_when_segmentation_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "segment_subtitles",
        lambda *_args, **_kwargs: SimpleNamespace(
            entries=[
                SimpleNamespace(start=20.0, end=22.0, text_raw="第一段", text_norm="第一段"),
                SimpleNamespace(start=22.0, end=24.0, text_raw="第二段", text_norm="第二段"),
            ]
        ),
    )

    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 7,
                "start_time": 20.0,
                "end_time": 24.0,
                "text_raw": "第一段第二段",
                "text_norm": "第一段第二段",
                "text_final": "第一段第二段",
                "words": [
                    {"word": "第一段", "start": 20.0, "end": 22.0},
                    {"word": "第二段", "start": 22.0, "end": 24.0},
                ],
            }
        ]
    )

    assert [row["text_final"] for row in rows] == ["第一段", "第二段"]
    assert rows[0]["split_strategy"] == "subtitle_segmentation_word_timed"
    assert rows[0]["split_attempted"] is True
    assert rows[0]["split_piece_timing_source"] == "segmented_word_timing"

    diagnostics = _manual_editor_source_row_split_diagnostics(rows)

    assert diagnostics["attempted_row_count"] == 1
    assert diagnostics["fragmented_row_count"] == 1
    assert diagnostics["fragment_count"] == 2
    assert diagnostics["recomputed_timing_count"] == 0
    assert diagnostics["strategy_counts"] == {"subtitle_segmentation_word_timed": 1}


def test_manual_editor_split_long_rows_preserve_flashlight_model_aliases_per_piece() -> None:
    context = "20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4"
    raw_text = "长度呢也没有比这个二三或者三七长很多。37跟23的长度是一模一样的。"
    corrected_text = _manual_editor_apply_source_text_corrections(raw_text, context_text=context)
    words = [
        {"word": char, "start": index * 0.12, "end": (index + 1) * 0.12}
        for index, char in enumerate(raw_text)
        if not char.isspace()
    ]

    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 5,
                "start_time": 0.0,
                "end_time": 8.0,
                "text_raw": raw_text,
                "text_norm": corrected_text,
                "text_final": corrected_text,
                "words": words,
            }
        ],
        context_text=context,
    )

    rendered = [str(row.get("text_final") or "") for row in rows]
    assert any("EDC23或者EDC37" in text for text in rendered)
    assert any("EDC37跟EDC23" in text for text in rendered)


def test_manual_editor_subtitle_projection_drops_final_empty_fillers() -> None:
    cleaned = _clean_manual_editor_subtitle_projection(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "呃，嗯。"},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": "型号：FX1（黑色）！"},
        ]
    )

    assert cleaned == [
        {
            "index": 1,
            "start_time": 1.0,
            "end_time": 2.0,
            "text_final": "型号 FX1 黑色",
        }
    ]


def test_manual_editor_subtitle_projection_can_keep_empty_fillers_for_source_transcript() -> None:
    cleaned = _clean_manual_editor_subtitle_projection(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_raw": "呃，嗯。", "text_final": "呃，嗯。"},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": "型号：FX1（黑色）！"},
        ],
        drop_empty=False,
    )

    assert cleaned == [
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "呃，嗯。",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
        },
        {
            "index": 1,
            "start_time": 1.0,
            "end_time": 2.0,
            "text_final": "型号 FX1 黑色",
        },
    ]


def test_manual_editor_subtitle_payload_preserves_standalone_fillers_for_full_editing() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 0.4,
            "text_raw": "嗯",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
        },
        index=0,
    )

    assert payload.text_final == "嗯"
    assert payload.text_raw == "嗯"


def test_manual_editor_subtitle_payload_uses_corrected_text_as_alignment_canonical() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "NNOCOC的的这个个发发售售太太难难了了",
            "text_final": "NOC的这个发售太难了",
            "words": [
                {"word": char, "start": index * 0.05, "end": (index + 1) * 0.05}
                for index, char in enumerate("NNOCOC的的这个个发发售售太太难难了了")
            ],
        },
        index=0,
    )

    assert payload.text_final == "NOC的这个发售太难了"
    assert "".join(word.word for word in payload.words) == "NOC的这个发售太难了"
    assert "".join(token.text for token in payload.alignment_tokens) == "NOC的这个发售太难了"


def test_manual_editor_source_projection_can_preserve_repeat_runs_for_review() -> None:
    repeated = "刚才我发现那个盒子放底下有点黑看不清它的这个全貌"
    cleaned = _clean_manual_editor_subtitle_projection(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": repeated},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": repeated},
            {"index": 2, "start_time": 2.0, "end_time": 3.0, "text_final": repeated},
            {"index": 3, "start_time": 3.0, "end_time": 4.0, "text_final": repeated},
        ],
        drop_empty=False,
        collapse_repeats=False,
    )

    assert [item["index"] for item in cleaned] == [0, 1, 2, 3]


def test_manual_editor_source_transcript_adds_orphan_word_rows() -> None:
    rows = _attach_manual_editor_words_to_subtitles(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "前一句"},
            {"index": 1, "start_time": 3.2, "end_time": 4.0, "text_final": "后一句"},
        ],
        [
            {"word": "然", "start": 1.6, "end": 1.72, "source": "provider"},
            {"word": "后", "start": 1.72, "end": 1.9, "source": "provider"},
            {"word": "呢", "start": 1.9, "end": 2.04, "source": "provider"},
        ],
    )

    assert [item["text_final"] for item in rows] == ["前一句", "然后呢", "后一句"]
    assert rows[1]["start_time"] == 1.6
    assert rows[1]["end_time"] == 2.04
    assert rows[1]["words"][0]["word"] == "然"


def test_manual_editor_words_inside_subtitle_ranges_do_not_override_source_text() -> None:
    rows = _attach_manual_editor_words_to_subtitles(
        [
            {"index": 0, "start_time": 1.2, "end_time": 3.0, "text_final": "今天主题"},
            {"index": 1, "start_time": 3.0, "end_time": 4.0, "text_final": "一把是EDC37"},
        ],
        [
            {"word": "啊", "start": 1.2, "end": 1.3, "source": "provider"},
            {"word": "呃", "start": 1.3, "end": 1.4, "source": "provider"},
            {"word": "今", "start": 1.4, "end": 1.5, "source": "provider"},
            {"word": "天", "start": 1.5, "end": 1.6, "source": "provider"},
            {"word": "主", "start": 1.6, "end": 1.7, "source": "provider"},
            {"word": "题", "start": 1.7, "end": 1.8, "source": "provider"},
            {"word": "这", "start": 2.7, "end": 2.8, "source": "provider"},
            {"word": "个", "start": 2.8, "end": 2.9, "source": "provider"},
            {"word": "一", "start": 3.0, "end": 3.1, "source": "provider"},
            {"word": "把", "start": 3.1, "end": 3.2, "source": "provider"},
            {"word": "是", "start": 3.2, "end": 3.3, "source": "provider"},
            {"word": "EDC37", "start": 3.3, "end": 3.7, "source": "provider"},
        ],
    )

    assert [item["text_final"] for item in rows] == ["今天主题", "一把是EDC37"]
    assert all(not item.get("virtual") for item in rows)


def test_manual_editor_word_order_noise_cannot_fragment_canonical_subtitle_text() -> None:
    rows = _attach_manual_editor_words_to_subtitles(
        [
            {"index": 0, "start_time": 17.0, "end_time": 18.9, "text_final": "NOC的这个发售啊太难了"},
            {"index": 1, "start_time": 18.9, "end_time": 20.8, "text_final": "太难了，难上加难"},
        ],
        [
            {"word": "NOC", "start": 17.0, "end": 17.25, "source": "provider"},
            {"word": "的", "start": 17.25, "end": 17.3, "source": "provider"},
            {"word": "这", "start": 17.3, "end": 17.4, "source": "provider"},
            {"word": "个", "start": 17.4, "end": 17.5, "source": "provider"},
            {"word": "发", "start": 17.5, "end": 17.62, "source": "provider"},
            {"word": "售", "start": 17.62, "end": 17.74, "source": "provider"},
            {"word": "啊", "start": 17.74, "end": 17.86, "source": "provider"},
            {"word": "太", "start": 17.86, "end": 18.0, "source": "provider"},
            {"word": "难", "start": 18.0, "end": 18.12, "source": "provider"},
            {"word": "太", "start": 18.9, "end": 19.0, "source": "provider"},
            {"word": "了", "start": 19.0, "end": 19.08, "source": "provider"},
            {"word": "难", "start": 19.08, "end": 19.18, "source": "provider"},
            {"word": "难", "start": 19.18, "end": 19.28, "source": "provider"},
            {"word": "上", "start": 19.28, "end": 19.38, "source": "provider"},
            {"word": "加", "start": 19.38, "end": 19.48, "source": "provider"},
            {"word": "难", "start": 19.48, "end": 19.58, "source": "provider"},
        ],
    )

    assert [item["text_final"] for item in rows] == [
        "NOC的这个发售啊太难了",
        "太难了，难上加难",
    ]
    assert "了太了" not in "".join(item["text_final"] for item in rows)


def test_manual_editor_source_text_correction_normalizes_flashlight_model_aliases() -> None:
    context = "20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4"

    assert _manual_editor_apply_source_text_corrections("所以呢我的选择就是这个幺七", context_text=context) == "所以呢我的选择就是这个EDC17"
    assert _manual_editor_apply_source_text_corrections("为什么三七一直没换", context_text=context) == "为什么EDC37一直没换"


def test_manual_editor_source_text_correction_normalizes_flashlight_numeric_comparisons() -> None:
    context = "20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4"

    assert (
        _manual_editor_apply_source_text_corrections(
            "37跟23的长度是一模一样的",
            context_text=context,
        )
        == "EDC37跟EDC23的长度是一模一样的"
    )


def test_manual_editor_source_text_correction_normalizes_flashlight_model_spellings() -> None:
    context = "20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4"

    assert _manual_editor_apply_source_text_corrections("它算是定位相当高端的一款EC手电了", context_text=context) == "它算是定位相当高端的一款EDC手电了"
    assert _manual_editor_apply_source_text_corrections("我记得是那个UHD二零了", context_text=context) == "我记得是那个UHD20了"


def test_manual_editor_source_text_correction_normalizes_noc_sale_mishear() -> None:
    context = "20260212-134637 开箱NOC MT34 也叫S06mini 折刀，还有玩法展示.mp4 抢购 一刀难求"

    assert _manual_editor_apply_source_text_corrections("我最近这三次最近这个发烧啊", context_text=context) == "我最近这三次最近这个发售啊"
    assert _manual_editor_apply_source_text_corrections("这两次抢那个两次发烧都是极限赶涨", context_text=context) == "这两次抢那个两次发售都是极限赶涨"
    assert _manual_editor_apply_source_text_corrections("这个发烧友很懂", context_text=context) == "这个发烧友很懂"


def test_manual_editor_canonical_source_rows_keep_text_authority_over_words() -> None:
    rows = _manual_editor_canonical_segment_source_rows(
        {
            "segments": [
                {
                    "index": 7,
                    "start": 17.0,
                    "end": 20.8,
                    "text_raw": "太难了，难上加难",
                    "text_canonical": "太难了，难上加难",
                    "words": [
                        {"word": "太", "start": 17.0, "end": 17.1},
                        {"word": "了", "start": 17.1, "end": 17.2},
                        {"word": "难", "start": 17.2, "end": 17.3},
                    ],
                }
            ]
        },
        context_text="NOC MT34",
    )

    assert rows[0]["text_final"] == "太难了，难上加难"
    assert "".join(word["word"] for word in rows[0]["words"]) == "太了难"


def test_manual_editor_canonical_source_rows_reveal_raw_asr_fillers() -> None:
    rows = _manual_editor_canonical_segment_source_rows(
        {
            "segments": [
                {
                    "index": 7,
                    "start": 17.0,
                    "end": 20.8,
                    "text_raw": "NOC的这个发售啊太难了",
                    "text_canonical": "NOC的这个发售太难了",
                    "display_suppressed_reason": "standalone_filler",
                    "words": [
                        {"word": char, "start": 17.0 + index * 0.1, "end": 17.1 + index * 0.1}
                        for index, char in enumerate("NOC的这个发售太难了")
                    ],
                }
            ]
        },
        context_text="NOC MT34",
    )

    assert rows[0]["text_final"] == "NOC的这个发售啊太难了"
    assert rows[0]["text_raw"] == "NOC的这个发售啊太难了"
    assert rows[0]["text_norm"] == "NOC的这个发售太难了"
    assert rows[0]["display_suppressed_reason"] == "standalone_filler"


def test_manual_editor_subtitle_items_can_serve_as_legacy_source_fallback() -> None:
    rows = _manual_editor_subtitle_item_source_rows(
        [
            SimpleNamespace(
                item_index=2,
                start_time=12.9,
                end_time=20.06,
                text_raw="最近这三次NOC的发烧太难了",
                text_norm="最近这三次NOC的发烧太难了",
                text_final="最近这三次NOC的发烧太难了",
            )
        ],
        context_text="20260212-134637 开箱NOC MT34 也叫S06mini 折刀 抢购 一刀难求",
    )

    assert rows == [
        {
            "index": 2,
            "source_index": 2,
            "source_indexes": [2],
            "start_time": 12.9,
            "end_time": 20.06,
            "text_raw": "最近这三次NOC的发烧太难了",
            "text_norm": "最近这三次NOC的发烧太难了",
            "text_final": "最近这三次NOC的发烧太难了",
            "timing_text": "最近这三次NOC的发烧太难了",
            "display_suppressed_reason": None,
            "projection_source": "subtitle_item",
        }
    ]


def test_manual_editor_subtitle_item_source_rows_respect_surface_contract() -> None:
    rows = _manual_editor_subtitle_item_source_rows(
        [
            SimpleNamespace(
                item_index=7,
                start_time=2.0,
                end_time=4.0,
                text_raw="它算是定位相当高端的一款EC手电了",
                text_norm="它算是定位相当高端的一款EDC手电了",
                text_final="",
                display_suppressed_reason="standalone_filler",
            )
        ],
        context_text="EDC17 开箱",
    )

    assert rows == []


def test_manual_editor_transcript_source_rows_do_not_apply_early_term_corrections() -> None:
    rows = _manual_editor_transcript_source_rows(
        [
            SimpleNamespace(
                version=1,
                segment_index=3,
                start_time=12.0,
                end_time=14.0,
                text="我记得是那个UHD二零了",
                words_json=[{"word": "我", "start": 12.0, "end": 12.1}],
            )
        ],
        context_text="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
    )

    assert rows[0]["text_raw"] == "我记得是那个UHD二零了"
    assert rows[0]["text_norm"] == "我记得是那个UHD二零了"
    assert rows[0]["text_final"] == "我记得是那个UHD二零了"
    assert rows[0]["display_suppressed_reason"] is None


def test_manual_editor_canonical_source_rows_do_not_apply_early_term_corrections() -> None:
    rows = _manual_editor_canonical_segment_source_rows(
        {
            "segments": [
                {
                    "index": 2,
                    "start": 10.0,
                    "end": 12.0,
                    "text_raw": "所以呢我的选择就是这个幺七",
                    "text_canonical": "所以呢我的选择就是这个幺七",
                }
            ]
        },
        context_text="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
    )

    assert rows[0]["text_raw"] == "所以呢我的选择就是这个幺七"
    assert rows[0]["text_norm"] == "所以呢我的选择就是这个幺七"
    assert rows[0]["text_final"] == "所以呢我的选择就是这个幺七"


def test_manual_editor_transcript_source_rows_drop_redundant_synthetic_duplicate_words() -> None:
    rows = _manual_editor_transcript_source_rows(
        [
            SimpleNamespace(
                version=1,
                segment_index=11,
                start_time=890.28,
                end_time=894.04,
                text="大拇指推这个快开桌啊，啊也是很轻松。",
                words_json=[
                    {"word": "大", "start": 890.28, "end": 890.36},
                    {"word": "拇", "start": 890.36, "end": 890.44},
                    {"word": "指", "start": 890.44, "end": 890.60},
                    {"word": "推", "start": 890.60, "end": 890.84},
                    {"word": "这", "start": 890.84, "end": 890.92},
                    {"word": "个", "start": 890.92, "end": 891.00},
                    {"word": "快", "start": 891.00, "end": 891.16},
                    {"word": "开", "start": 891.16, "end": 891.24},
                    {"word": "桌", "start": 891.32, "end": 891.48},
                    {
                        "word": "啊",
                        "start": 891.48,
                        "end": 891.481,
                        "raw_text": None,
                        "raw_payload": {"_roughcut_asr_normalization": {"matched": False}},
                    },
                    {
                        "word": "啊",
                        "start": 891.48,
                        "end": 892.84,
                        "raw_text": "啊",
                        "raw_payload": {"_roughcut_asr_normalization": {"matched": True}},
                    },
                    {"word": "也", "start": 892.84, "end": 893.00},
                    {"word": "是", "start": 893.00, "end": 893.16},
                ],
            )
        ],
        context_text="20260212-134637 开箱NOC MT34 也叫S06mini 折刀，还有玩法展示.mp4",
    )

    assert [word["word"] for word in rows[0]["words"]].count("啊") == 1


def test_manual_editor_choose_source_subtitle_rows_prefers_better_canonical_segmentation() -> None:
    transcript_rows = [
        {
            "index": 0,
            "start_time": 432.28,
            "end_time": 436.84,
            "text_final": "所以说为什么我平时比如临时出个门遛个狗啊这个",
            "words": [{"word": char, "start": 432.28 + index * 0.1, "end": 432.33 + index * 0.1} for index, char in enumerate("所以说为什么我平时比如临时出个门遛个狗啊这个")],
            "projection_source": "transcript_segment",
        },
        {
            "index": 1,
            "start_time": 436.84,
            "end_time": 439.96,
            "text_final": "或者说简单的这个",
            "words": [{"word": char, "start": 436.84 + index * 0.1, "end": 436.89 + index * 0.1} for index, char in enumerate("或者说简单的这个")],
            "projection_source": "transcript_segment",
        },
        {
            "index": 2,
            "start_time": 439.96,
            "end_time": 441.32,
            "text_final": "晚上出门都会带它很实用",
            "words": [{"word": char, "start": 439.96 + index * 0.1, "end": 440.01 + index * 0.1} for index, char in enumerate("晚上出门都会带它很实用")],
            "projection_source": "transcript_segment",
        },
        {
            "index": 3,
            "start_time": 443.0,
            "end_time": 446.12,
            "text_final": "而且它的这个UV的功能啊",
            "words": [{"word": char, "start": 443.0 + index * 0.1, "end": 443.05 + index * 0.1} for index, char in enumerate("而且它的这个UV的功能啊")],
            "projection_source": "transcript_segment",
        },
        {
            "index": 4,
            "start_time": 446.12,
            "end_time": 447.28,
            "text_final": "也不是说只限用照明",
            "words": [{"word": char, "start": 446.12 + index * 0.1, "end": 446.17 + index * 0.1} for index, char in enumerate("也不是说只限用照明")],
            "projection_source": "transcript_segment",
        },
    ]
    canonical_rows = [
        {
            "index": 0,
            "start_time": 432.28,
            "end_time": 436.84,
            "text_final": "所以说为什么我平时比如临时出个门遛个狗啊这个",
            "words": [{"word": char, "start": 432.28 + index * 0.1, "end": 432.33 + index * 0.1} for index, char in enumerate("所以说为什么我平时比如临时出个门遛个狗啊这个")],
            "projection_source": "canonical_transcript",
        },
        {
            "index": 1,
            "start_time": 436.84,
            "end_time": 441.32,
            "text_final": "或者说简单的这个短途的通勤啊晚上出门都会带它很实用",
            "words": [{"word": char, "start": 436.84 + index * 0.08, "end": 436.88 + index * 0.08} for index, char in enumerate("或者说简单的这个短途的通勤啊晚上出门都会带它很实用")],
            "projection_source": "canonical_transcript",
        },
        {
            "index": 2,
            "start_time": 443.0,
            "end_time": 447.28,
            "text_final": "而且它的这个UV的功能啊也不是说只限用照明",
            "words": [{"word": char, "start": 443.0 + index * 0.08, "end": 443.04 + index * 0.08} for index, char in enumerate("而且它的这个UV的功能啊也不是说只限用照明")],
            "projection_source": "canonical_transcript",
        },
    ]

    chosen = _manual_editor_choose_source_subtitle_rows(
        [
            ("transcript_segment", transcript_rows),
            ("canonical_transcript", canonical_rows),
        ]
    )

    assert chosen == canonical_rows


def test_manual_editor_projection_rows_as_source_rows_preserve_automatic_segmentation() -> None:
    rows = _manual_editor_projection_rows_as_source_rows(
        [
            {
                "index": 12,
                "start_time": 436.84,
                "end_time": 439.96,
                "text_raw": "或者说简单的这个短途的通勤啊，",
                "text_norm": "或者说简单的这个短途的通勤啊，",
                "text_final": "或者说简单的这个短途的通勤啊，",
                "words": [
                    {"word": "或者说", "start": 436.84, "end": 437.52},
                    {"word": "简单的", "start": 437.52, "end": 438.2},
                ],
            },
            {
                "index": 13,
                "start_time": 439.96,
                "end_time": 441.32,
                "text_raw": "这个晚上出门都会带它。",
                "text_norm": "这个晚上出门都会带它。",
                "text_final": "这个晚上出门都会带它。",
            },
        ],
        projection_data={"transcript_layer": "canonical_transcript"},
    )

    assert [row["text_final"] for row in rows] == [
        "或者说简单的这个短途的通勤啊，",
        "这个晚上出门都会带它。",
    ]
    assert [row["source_index"] for row in rows] == [12, 13]
    assert rows[0]["projection_source"] == "canonical_transcript"
    assert rows[0]["timing_text"] == "或者说简单的这个短途的通勤啊，"
    assert rows[0]["segmentation_locked"] is True


def test_manual_editor_projection_rows_as_source_rows_preserve_canonical_without_raw_fallback() -> None:
    rows = _manual_editor_projection_rows_as_source_rows(
        [
            {
                "index": 3,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "原始口播",
                "text_norm": "规范文本",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        projection_data={"transcript_layer": "canonical_transcript"},
    )

    assert rows == [
        {
            "index": 3,
            "source_index": 3,
            "source_indexes": [3],
            "start_time": 1.0,
            "end_time": 2.0,
            "text_raw": "原始口播",
            "text_norm": "规范文本",
            "text_final": "",
            "timing_text": "规范文本",
            "words": [],
            "display_suppressed_reason": "standalone_filler",
            "projection_source": "canonical_transcript",
            "segmentation_locked": True,
        }
    ]


def test_manual_editor_source_alignment_preserves_locked_projection_boundaries() -> None:
    rows = _manual_editor_align_source_rows_to_asr_words(
        [
            {
                "index": 12,
                "start_time": 436.84,
                "end_time": 439.96,
                "text_final": "或者说简单的这个短途的通勤啊，",
                "projection_source": "canonical_transcript",
                "segmentation_locked": True,
            }
        ],
        [
            {"word": char, "start": 437.1 + index * 0.08, "end": 437.14 + index * 0.08}
            for index, char in enumerate("或者说简单的这个短途的通勤啊")
        ],
    )

    assert rows[0]["start_time"] == 436.84
    assert rows[0]["end_time"] == 439.96
    assert rows[0]["source_overlap_start_time"] >= 437.1
    assert rows[0]["source_overlap_end_time"] <= 439.96
    assert "".join(word["word"] for word in rows[0]["words"]).startswith("或者说简单")


def test_manual_editor_source_reveal_preserves_locked_projection_boundaries() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "今天主题",
                "projection_source": "canonical_transcript",
                "segmentation_locked": True,
            }
        ],
        [
            {"word": "啊", "start": 1.0, "end": 1.1, "source": "provider"},
            {"word": "今", "start": 1.1, "end": 1.2, "source": "provider"},
            {"word": "天", "start": 1.2, "end": 1.3, "source": "provider"},
            {"word": "主", "start": 1.3, "end": 1.4, "source": "provider"},
            {"word": "题", "start": 1.4, "end": 1.5, "source": "provider"},
            {"word": "吧", "start": 1.5, "end": 1.6, "source": "provider"},
        ],
    )

    assert rows[0]["start_time"] == 1.0
    assert rows[0]["end_time"] == 2.0
    assert rows[0]["transcript_text"] == "啊今天主题吧"


def test_manual_editor_split_source_fragments_assign_unique_indexes_when_source_index_missing() -> None:
    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "start_time": 1.6,
                "end_time": 15.747,
                "text_final": "哦今天终于收到了年前的最后的一款小玩具啊这个也是耗尽了我这次的欧",
                "words": [
                    {"word": "哦", "start": 1.6, "end": 2.08},
                    {"word": "今天", "start": 2.16, "end": 2.48},
                    {"word": "终于", "start": 2.96, "end": 3.44},
                    {"word": "收到了", "start": 3.44, "end": 4.16},
                    {"word": "年前的", "start": 4.48, "end": 5.28},
                    {"word": "最后的", "start": 6.24, "end": 6.72},
                    {"word": "一款", "start": 7.68, "end": 7.84},
                    {"word": "小玩具啊", "start": 8.0, "end": 8.56},
                    {"word": "这个也是", "start": 9.8, "end": 10.9},
                    {"word": "耗尽了", "start": 11.1, "end": 11.7},
                    {"word": "我这次的欧", "start": 12.0, "end": 13.4},
                ],
            }
        ],
        reindex_fragments=True,
    )

    indexes = [int(row["index"]) for row in rows]

    assert len(indexes) == len(set(indexes))
    assert indexes == sorted(indexes)


def test_manual_editor_split_long_rows_rebalances_flashlight_ascii_model_boundaries() -> None:
    context = "20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4"
    raw_text = (
        "这一千五你放到这儿，然后跟我们的EDC37简单对比一下吧，EDC37也是高档也是一千五啊。"
        "这个其实还挺不错，因为大家知道EDC37在奈特科尔产品线算是定位相当高端的一款E C手电了，"
        "它的灯珠也是规格相当高的，这个EDC17是什么灯珠啊？这个我记得是那个UHD二零了。"
    )
    words = [
        {"word": char, "start": index * 0.12, "end": (index + 1) * 0.12}
        for index, char in enumerate(raw_text)
        if not char.isspace()
    ]

    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 41,
                "start_time": 0.0,
                "end_time": 32.0,
                "text_raw": raw_text,
                "text_norm": raw_text,
                "text_final": raw_text,
                "transcript_text": raw_text,
                "words": words,
            }
        ],
        context_text=context,
    )

    rendered = [str(row.get("text_final") or "") for row in rows]
    assert any("EDC37简单对比一下吧" in text for text in rendered)
    assert any("EDC" in text and not text.endswith("EDC") for text in rendered)
    assert any("EDC17" in text for text in rendered)
    assert any("UHD20了" in text for text in rendered)
    assert not any(text.endswith("EDC1") for text in rendered)
    assert not any(text.startswith("7是什么灯珠") for text in rendered)


def test_manual_editor_split_source_fragments_reorder_by_time_before_reindex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jobs_module,
        "split_subtitle_display_item",
        lambda **_kwargs: [
            {"text": "第一段", "start_time": 0.0, "end_time": 3.0},
            {"text": "第二段", "start_time": 3.0, "end_time": 6.0},
            {"text": "第三段", "start_time": 6.0, "end_time": 9.0},
        ],
    )
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_split_piece_timings_from_words",
        lambda _item, _pieces: [
            (6.0, 7.0),
            (1.0, 2.0),
            (4.0, 5.0),
        ],
    )

    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 9,
                "start_time": 0.0,
                "end_time": 9.0,
                "text_final": "第一段第二段第三段",
                "words": [
                    {"word": "第一段", "start": 6.0, "end": 7.0},
                    {"word": "第二段", "start": 1.0, "end": 2.0},
                    {"word": "第三段", "start": 4.0, "end": 5.0},
                ],
            }
        ],
        reindex_fragments=True,
    )

    assert [(row["start_time"], row["end_time"]) for row in rows] == [
        (1.0, 2.0),
        (4.0, 5.0),
        (6.0, 7.0),
    ]
    assert [row["text_final"] for row in rows] == ["第二段", "第三段", "第一段"]
    assert [row["index"] for row in rows] == [0, 1, 2]
    assert [row["source_index"] for row in rows] == [0, 1, 2]
    assert [row["source_indexes"] for row in rows] == [[0], [1], [2]]


def test_manual_editor_split_source_fragments_preserve_spoken_text_raw_over_normalized_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs_module,
        "segment_subtitles",
        lambda *_args, **_kwargs: SimpleNamespace(
            entries=[
                SimpleNamespace(
                    start=228.6,
                    end=234.52,
                    text_raw="呃，看啊，这个刃面",
                    text_norm="呃，看啊，刃面。",
                    words=(
                        {"word": "呃，", "start": 228.6, "end": 229.0},
                        {"word": "看啊，", "start": 229.72, "end": 230.12},
                        {"word": "这个", "start": 230.12, "end": 230.44},
                        {"word": "刃面", "start": 234.12, "end": 234.52},
                    ),
                ),
                SimpleNamespace(
                    start=234.6,
                    end=240.441,
                    text_raw="抛的是完美无缺啊！哇塞，真是太帅了。",
                    text_norm="抛的是完美无缺啊！哇塞，真是太帅了。",
                    words=(
                        {"word": "抛的是", "start": 234.6, "end": 235.4},
                        {"word": "完美无缺啊！", "start": 236.2, "end": 237.0},
                    ),
                ),
            ]
        ),
    )

    rows = _manual_editor_split_long_subtitle_rows(
        [
            {
                "index": 3,
                "start_time": 225.0,
                "end_time": 240.441,
                "text_raw": "也还行，因为它不太不算疼嘛。呃，看啊，这个刃面抛的是完美无缺啊！哇塞，真是太帅了。",
                "text_final": "也还行，因为它不太不算疼嘛。呃，看啊，这个刃面抛的是完美无缺啊！哇塞，真是太帅了。",
                "words": [
                    {"word": "呃，", "start": 228.6, "end": 229.0},
                    {"word": "看啊，", "start": 229.72, "end": 230.12},
                    {"word": "这个", "start": 230.12, "end": 230.44},
                    {"word": "刃面", "start": 234.12, "end": 234.52},
                    {"word": "抛的是", "start": 234.6, "end": 235.4},
                    {"word": "完美无缺啊！", "start": 236.2, "end": 237.0},
                ],
            }
        ]
    )

    assert [row["text_final"] for row in rows] == [
        "呃，看啊，刃面。",
        "抛的是完美无缺啊！哇塞，真是太帅了。",
    ]
    assert [row["text_raw"] for row in rows] == [
        "呃，看啊，这个刃面",
        "抛的是完美无缺啊！哇塞，真是太帅了。",
    ]
    assert [row["text_norm"] for row in rows] == [
        "呃，看啊，刃面。",
        "抛的是完美无缺啊！哇塞，真是太帅了。",
    ]
    assert [row["timing_text"] for row in rows] == [
        "呃，看啊，这个刃面",
        "抛的是完美无缺啊！哇塞，真是太帅了。",
    ]


def test_manual_editor_source_asr_words_reveal_fillers_hidden_by_canonical_text() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "今天主题",
                "text_final": "今天主题",
                "projection_source": "canonical_transcript",
            }
        ],
        [
            {"word": "啊", "start": 1.0, "end": 1.1, "source": "provider"},
            {"word": "呃", "start": 1.1, "end": 1.2, "source": "provider"},
            {"word": "今", "start": 1.2, "end": 1.3, "source": "provider"},
            {"word": "天", "start": 1.3, "end": 1.4, "source": "provider"},
            {"word": "主", "start": 1.4, "end": 1.5, "source": "provider"},
            {"word": "题", "start": 1.5, "end": 1.6, "source": "provider"},
            {"word": "吧", "start": 1.6, "end": 1.7, "source": "provider"},
        ],
    )

    assert rows[0]["text_final"] == "今天主题"
    assert rows[0]["transcript_text_raw"] == "啊呃今天主题吧"
    assert rows[0]["transcript_text"] == "啊呃今天主题吧"
    assert "".join(word["word"] for word in rows[0]["words"]) == "啊呃今天主题吧"


def test_manual_editor_orphan_word_subtitles_expose_transcript_source_basis() -> None:
    rows = jobs_module._manual_editor_orphan_word_subtitles(
        [],
        [
            {"word": "啊", "start": 1.0, "end": 1.1},
            {"word": "呃", "start": 1.1, "end": 1.2},
            {"word": "今", "start": 1.2, "end": 1.3},
            {"word": "天", "start": 1.3, "end": 1.4},
        ],
    )

    assert rows == [
        {
            "index": 0,
            "source_index": 0,
            "source_indexes": [0],
            "start_time": 1.0,
            "end_time": 1.4,
            "text_raw": "啊呃今天",
            "text_norm": "啊呃今天",
            "text_final": "啊呃今天",
            "display_suppressed_reason": None,
            "projection_source": "transcript_segment",
            "words": [
                {"word": "啊", "start": 1.0, "end": 1.1},
                {"word": "呃", "start": 1.1, "end": 1.2},
                {"word": "今", "start": 1.2, "end": 1.3},
                {"word": "天", "start": 1.3, "end": 1.4},
            ],
            "virtual": True,
        }
    ]


def test_manual_editor_revealed_asr_words_keep_raw_and_corrected_transcript_texts_separate() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "它算是定位相当高端的一款EDC手电了",
            }
        ],
        [
            {"word": char, "start": 1.0 + index * 0.05, "end": 1.04 + index * 0.05, "source": "provider"}
            for index, char in enumerate("它算是定位相当高端的一款EC手电了")
        ],
        context_text="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
    )

    assert rows[0]["transcript_text_raw"] == "它算是定位相当高端的一款EC手电了"
    assert rows[0]["transcript_text"] == "它算是定位相当高端的一款EDC手电了"


def test_manual_editor_source_rows_do_not_collapse_stutter_text_early() -> None:
    row = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.5,
            "text_raw": "最近这个发售发发售啊太难",
            "text_norm": "最近这个发售发发售啊太难",
            "text_final": "最近这个发售发发售啊太难",
        },
        index=0,
    )

    assert row.text_final == "最近这个发售发发售啊太难"


def test_manual_editor_source_asr_words_apply_hotword_corrections_without_hiding_fillers() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "EDC小玩具这个也",
                "projection_source": "canonical_transcript",
            }
        ],
        [
            {"word": "一", "start": 1.0, "end": 1.1},
            {"word": "滴", "start": 1.1, "end": 1.2},
            {"word": "西", "start": 1.2, "end": 1.3},
            {"word": "啊", "start": 1.3, "end": 1.4},
            {"word": "小", "start": 1.4, "end": 1.5},
            {"word": "玩", "start": 1.5, "end": 1.6},
            {"word": "具", "start": 1.6, "end": 1.7},
        ],
        hotword_replacements=[("一滴西", "EDC")],
    )

    assert rows[0]["text_final"] == "EDC小玩具这个也"
    assert rows[0]["transcript_text"] == "EDC啊小玩具"
    assert "".join(word["word"] for word in rows[0]["words"]) == "一滴西啊小玩具"


def test_manual_editor_transcript_hotword_corrections_preserve_spoken_repeats() -> None:
    corrected = _manual_editor_apply_transcript_hotword_corrections(
        "太太难了一滴西啊",
        hotword_replacements=[("一滴西", "EDC")],
    )

    assert corrected == "太太难了EDC啊"


def test_manual_editor_vertical_glossary_requires_content_profile_evidence() -> None:
    assert not _manual_editor_profile_has_vertical_glossary_evidence({})
    assert not _manual_editor_profile_has_vertical_glossary_evidence({"subject_domain": "edc"})
    assert _manual_editor_profile_has_vertical_glossary_evidence(
        {"subject_domain": "edc", "subject_brand": "NOC", "subject_model": "MT34"}
    )


def test_manual_editor_raw_word_payload_can_use_raw_asr_text_for_source_display() -> None:
    payload = _manual_editor_word_payload(
        {
            "word": "这",
            "raw_text": "啊",
            "start": 1.2,
            "end": 1.3,
            "provider": "local_http_asr",
        },
        prefer_raw_text=True,
    )

    assert payload is not None
    assert payload.word == "啊"


def test_manual_editor_subtitle_payload_exposes_transcript_text_without_replacing_final_text() -> None:
    payload = _manual_editor_subtitle_payload(
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 2.0,
            "text_final": "一个小玩具这个也",
            "transcript_text": "一个小玩具啊这个也",
            "projection_source": "canonical_transcript",
            "words": [
                {"word": char, "start": 1.0 + index * 0.1, "end": 1.1 + index * 0.1}
                for index, char in enumerate("一个小玩具啊这个也")
            ],
        },
        index=0,
    )

    assert payload.text_final == "一个小玩具这个也"
    assert payload.projection_source == "canonical_transcript"
    assert payload.transcript_text == "一个小玩具啊这个也"
    assert "".join(word.word for word in payload.words) == "一个小玩具啊这个也"


def test_manual_editor_source_asr_words_do_not_replace_mismatched_canonical_text() -> None:
    rows = _manual_editor_reveal_source_asr_words(
        [
            {
                "index": 0,
                "start_time": 17.0,
                "end_time": 20.8,
                "text_final": "太难了，难上加难",
                "projection_source": "canonical_transcript",
            }
        ],
        [
            {"word": "太", "start": 17.0, "end": 17.1},
            {"word": "了", "start": 17.1, "end": 17.2},
            {"word": "难", "start": 17.2, "end": 17.3},
        ],
    )

    assert rows[0]["text_final"] == "太难了，难上加难"
    assert rows[0]["transcript_text"] == "太了难"


def test_manual_editor_canonical_source_does_not_add_global_orphan_word_rows() -> None:
    rows = _attach_manual_editor_words_to_subtitles(
        [
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 3.0,
                "text_final": "完整正文已经来自canonical",
                "projection_source": "canonical_transcript",
            }
        ],
        [{"word": "碎", "start": 1.2, "end": 1.201, "source": "provider"}],
    )

    assert len(rows) == 1
    assert rows[0]["text_final"] == "完整正文已经来自canonical"


def test_manual_editor_source_transcript_drops_orphan_boundary_duplicates() -> None:
    rows = _attach_manual_editor_words_to_subtitles(
        [
            {"index": 0, "start_time": 17.0, "end_time": 18.9, "text_final": "NOC的这个发售太难了"},
            {"index": 1, "start_time": 19.2, "end_time": 20.8, "text_final": "太难了难上加难"},
        ],
        [
            {"word": "难", "start": 19.02, "end": 19.1, "source": "provider"},
        ],
    )

    assert [item["text_final"] for item in rows] == ["NOC的这个发售太难了", "太难了难上加难"]


def test_manual_editor_subtitle_projection_collapses_asr_repeat_runs() -> None:
    repeated = "刚才我发现那个盒子放底下有点黑看不清它的这个全貌"
    cleaned = _clean_manual_editor_subtitle_projection(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": repeated},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": repeated},
            {"index": 2, "start_time": 2.0, "end_time": 3.0, "text_final": repeated},
            {"index": 3, "start_time": 3.0, "end_time": 4.0, "text_final": repeated},
            {"index": 4, "start_time": 4.0, "end_time": 5.0, "text_final": "下一句正常内容"},
        ]
    )

    assert [item["index"] for item in cleaned] == [0, 4]


def test_manual_editor_subtitle_projection_detects_three_item_repeat_run() -> None:
    repeated = "刚才我发现那个盒子放底下有点黑看不清它的这个全貌"
    raw = [
        {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": repeated},
        {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": repeated},
        {"index": 2, "start_time": 2.0, "end_time": 3.0, "text_final": repeated},
    ]

    cleaned = _clean_manual_editor_subtitle_projection(raw)

    assert [item["index"] for item in cleaned] == [0]
    assert _manual_editor_has_collapsed_repeat_runs(raw, cleaned)


def test_manual_editor_uses_clean_fallback_when_cleaning_drops_repeats() -> None:
    repeated = "刚才我发现那个盒子放底下有点黑看不清它的这个全貌"
    raw = [
        {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": repeated},
        {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": repeated},
        {"index": 2, "start_time": 2.0, "end_time": 3.0, "text_final": repeated},
    ]
    cleaned = _clean_manual_editor_subtitle_projection(raw)

    assert _manual_editor_should_use_clean_fallback_projection(
        raw,
        cleaned,
        {"projection_kind": "display_baseline", "transcript_layer": "canonical_transcript"},
    )
    assert _manual_editor_projection_data_uses_canonical(
        {"projection_kind": "display_baseline", "transcript_layer": "canonical_transcript"}
    )
    assert _manual_editor_projection_entries_use_canonical(
        [{"index": 0, "projection_source": "canonical_transcript"}]
    )
    assert _manual_editor_should_use_clean_fallback_projection(
        raw,
        cleaned,
        {"projection_kind": "legacy"},
    )
    assert not _manual_editor_projection_data_uses_canonical({"projection_kind": "legacy"})
    assert not _manual_editor_projection_entries_use_canonical([{"index": 0}])


@pytest.mark.asyncio
async def test_edited_subtitle_projection_keeps_fallback_text_instead_of_canonical() -> None:
    projected = await _build_edited_subtitle_projection(
        None,
        job_id=uuid4(),
        keep_segments=[{"start": 0.0, "end": 10.0}],
        projection_data={"projection_kind": "display_baseline", "transcript_layer": "canonical_transcript"},
        fallback_subtitles=[
            {
                "index": 2,
                "start_time": 1.0,
                "end_time": 4.0,
                "text_final": "最近这三次NOC的发售太难了",
            }
        ],
    )

    assert [item["text_final"] for item in projected] == ["最近这三次NOC的发售太难了"]


@pytest.mark.asyncio
async def test_edited_subtitle_projection_prefers_current_projection_entries_over_collapsed_fallback_source() -> None:
    projected = await _build_edited_subtitle_projection(
        None,
        job_id=uuid4(),
        keep_segments=[
            {"start": 1.56, "end": 5.85},
            {"start": 6.08, "end": 8.0},
        ],
        projection_data={
            "transcript_layer": "subtitle_item",
            "split_profile": {"max_chars": 30, "max_duration": 5.0},
            "entries": [
                {
                    "index": 0,
                    "start_time": 1.6,
                    "end_time": 4.0,
                    "text_final": "第一条",
                },
                {
                    "index": 1,
                    "start_time": 6.1,
                    "end_time": 7.4,
                    "text_final": "第二条",
                },
            ],
        },
        fallback_subtitles=[
            {
                "index": 0,
                "start_time": 1.6,
                "end_time": 7.4,
                "text_final": "被压扁的一整条源字幕",
            }
        ],
    )

    assert [item["text_final"] for item in projected] == ["第一条", "第二条"]
    assert projected[0]["start_time"] == pytest.approx(0.04)
    assert projected[1]["start_time"] == pytest.approx(4.31)


@pytest.mark.asyncio
async def test_edited_subtitle_projection_can_use_source_baseline_for_production_output() -> None:
    projected = await _build_edited_subtitle_projection(
        None,
        job_id=uuid4(),
        keep_segments=[
            {"start": 1.0, "end": 2.0},
            {"start": 3.0, "end": 4.0},
        ],
        projection_data={
            "transcript_layer": "subtitle_projection",
            "entries": [
                {
                    "index": 0,
                    "start_time": 1.0,
                    "end_time": 4.0,
                    "text_final": "展示投影文本",
                },
            ],
        },
        fallback_subtitles=[
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "源字幕第一条",
            },
            {
                "index": 1,
                "start_time": 3.0,
                "end_time": 4.0,
                "text_final": "源字幕第二条",
            },
        ],
        prefer_source_subtitles=True,
    )

    assert [item["text_final"] for item in projected] == ["源字幕第一条", "源字幕第二条"]
    assert projected[0]["start_time"] == pytest.approx(0.0)
    assert projected[1]["start_time"] == pytest.approx(1.0)


def test_project_canonical_transcript_to_timeline_prefers_explicit_canonical_surface_from_segmentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "roughcut.pipeline.steps.segment_subtitles",
        lambda *_args, **_kwargs: SimpleNamespace(
            entries=[
                SimpleNamespace(
                    index=0,
                    start=1.0,
                    end=4.0,
                    text_raw="你看到的是EC手电",
                    text_norm="你看到的是EDC手电",
                )
            ]
        ),
    )

    projected = _project_canonical_transcript_to_timeline(
        {
            "segments": [
                {
                    "index": 2,
                    "start": 1.0,
                    "end": 4.0,
                    "text_raw": "你看到的是EC手电",
                    "text_canonical": "你看到的是EDC手电",
                    "words": [
                        {"word": "你看到的是", "start": 1.0, "end": 2.0},
                        {"word": "EC手电", "start": 2.0, "end": 4.0},
                    ],
                }
            ]
        },
        keep_segments=[{"start": 0.0, "end": 10.0}],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )

    assert projected == [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 4.0,
            "text_raw": "你看到的是EC手电",
            "text_norm": "你看到的是EDC手电",
            "text_final": "你看到的是EDC手电",
            "projection_source": "canonical_transcript",
        }
    ]


def test_manual_editor_subtitle_projection_keeps_short_repeated_pairs() -> None:
    cleaned = _clean_manual_editor_subtitle_projection(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "这个是真的"},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": "这个是真的"},
        ]
    )

    assert [item["index"] for item in cleaned] == [0, 1]


def test_manual_editor_subtitle_projection_preserves_projection_bridge_clauses_when_not_final_cleaning() -> None:
    raw = [
        {
            "index": 0,
            "start_time": 181.03,
            "end_time": 182.076,
            "text_raw": "然后，呃，首先",
            "text_norm": "然后， 呃， 首先",
            "text_final": "然后， 呃， 首先",
        },
        {
            "index": 1,
            "start_time": 184.865,
            "end_time": 188.003,
            "text_raw": "这个就是M的这个标，你长按",
            "text_norm": "这个就是M的这个标， 你长按",
            "text_final": "这个就是M的这个标， 你长按",
        },
    ]

    cleaned = _clean_manual_editor_subtitle_projection(
        raw,
        clean_text=False,
        collapse_repeats=False,
    )

    assert [item["text_final"] for item in cleaned] == [
        "然后， 呃， 首先",
        "这个就是M的这个标， 你长按",
    ]


def test_manual_editor_projection_baseline_rows_do_not_apply_final_subtitle_cleanup() -> None:
    rows = _manual_editor_projection_baseline_rows(
        projected_subtitles=[
            {
                "index": 0,
                "start_time": 181.03,
                "end_time": 182.076,
                "text_raw": "然后，呃，首先",
                "text_norm": "然后， 呃， 首先",
                "text_final": "然后， 呃， 首先",
            },
            {
                "index": 1,
                "start_time": 184.865,
                "end_time": 188.003,
                "text_raw": "这个就是M的这个标，你长按",
                "text_norm": "这个就是M的这个标， 你长按",
                "text_final": "这个就是M的这个标， 你长按",
            },
        ],
        source_subtitles=[],
    )

    assert [item["text_final"] for item in rows] == [
        "然后， 呃， 首先",
        "这个就是M的这个标， 你长按",
    ]


@pytest.mark.asyncio
async def test_manual_editor_source_subtitles_use_projection_rows_only_after_source_fact_candidates_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        async def get(self, model: object, job_id: object) -> SimpleNamespace:
            return SimpleNamespace(source_name="测试视频")

        async def execute(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    async def _unexpected_projection_loader(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cached projection rows should prevent reloading projection entries")

    async def _fake_load_latest_optional_artifact(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        jobs_module,
        "_load_manual_editor_latest_subtitle_projection_entries",
        _unexpected_projection_loader,
    )

    rows = await _load_manual_editor_source_subtitle_dicts(
        _FakeSession(),
        job_id=uuid4(),
        latest_projection_rows=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 2.4,
                "text_raw": "自动投影切分",
                "text_norm": "自动投影切分",
                "text_final": "自动投影切分",
            }
        ],
        latest_projection_data={
            "transcript_layer": "canonical_transcript",
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
        },
    )

    assert [row["text_final"] for row in rows] == ["自动投影切分"]


@pytest.mark.asyncio
async def test_manual_editor_source_subtitles_prefer_transcript_rows_over_projection_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript_rows = [
        SimpleNamespace(
            version=1,
            segment_index=0,
            start_time=26.3,
            end_time=28.673,
            text="没想到啊NOC现在这么火",
            words_json=[
                {"word": "没想到啊", "start": 26.3, "end": 26.9},
                {"word": "NOC", "start": 26.9, "end": 27.6},
                {"word": "现在这么火", "start": 27.6, "end": 28.673},
            ],
        )
    ]

    class _FakeSession:
        def __init__(self) -> None:
            self._execute_calls = 0

        async def get(self, model: object, job_id: object) -> SimpleNamespace:
            return SimpleNamespace(source_name="auto-demo.mp4")

        async def execute(self, *_args: object, **_kwargs: object) -> object:
            self._execute_calls += 1
            rows = transcript_rows if self._execute_calls == 1 else []
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    async def _fake_load_latest_optional_artifact(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)

    rows = await _load_manual_editor_source_subtitle_dicts(
        _FakeSession(),
        job_id=uuid4(),
        latest_projection_rows=[
            {
                "index": 8,
                "start_time": 24.7,
                "end_time": 27.073,
                "source_overlap_start_time": 26.3,
                "source_overlap_end_time": 28.673,
                "text_raw": "没想到啊NOC现在这么火",
                "text_norm": "没想到啊NOC现在这么火",
                "text_final": "没想到啊NOC现在这么火",
                "projection_source": "canonical_transcript",
            }
        ],
        latest_projection_data={
            "transcript_layer": "canonical_transcript",
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
        },
    )

    assert [row["text_final"] for row in rows] == ["没想到啊NOC现在这么火"]
    assert rows[0]["projection_source"] == "transcript_segment"
    assert "segmentation_locked" not in rows[0]


@pytest.mark.asyncio
async def test_rebuilt_canonical_projection_rows_do_not_override_transcript_source_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript_rows = [
        SimpleNamespace(
            version=1,
            segment_index=0,
            start_time=26.3,
            end_time=28.673,
            text="真实来源字幕",
            words_json=[
                {"word": "真实", "start": 26.3, "end": 27.0},
                {"word": "来源字幕", "start": 27.0, "end": 28.673},
            ],
        )
    ]

    class _FakeSession:
        def __init__(self) -> None:
            self._execute_calls = 0

        async def get(self, model: object, job_id: object) -> SimpleNamespace:
            return SimpleNamespace(source_name="auto-demo.mp4")

        async def execute(self, *_args: object, **_kwargs: object) -> object:
            self._execute_calls += 1
            rows = transcript_rows if self._execute_calls == 1 else []
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    async def _fake_load_latest_optional_artifact(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)

    rows = await _load_manual_editor_source_subtitle_dicts(
        _FakeSession(),
        job_id=uuid4(),
        latest_projection_rows=[
            {
                "index": 8,
                "start_time": 24.7,
                "end_time": 27.073,
                "source_overlap_start_time": 26.3,
                "source_overlap_end_time": 28.673,
                "text_raw": "没想到啊NOC现在这么火",
                "text_norm": "没想到啊NOC现在这么火",
                "text_final": "没想到啊NOC现在这么火",
                "projection_source": "canonical_transcript",
            }
        ],
        latest_projection_data={
            "transcript_layer": "canonical_transcript",
            "rebuilt_from_canonical_fallback": True,
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
            "split_profile": {"max_chars": 20, "max_duration": 3.8},
        },
    )

    assert [row["text_final"] for row in rows] == ["真实来源字幕"]
    assert rows[0]["projection_source"] == "transcript_segment"


@pytest.mark.asyncio
async def test_manual_editor_source_subtitles_preserve_cached_projection_text_without_recleaning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        async def get(self, model: object, job_id: object) -> SimpleNamespace:
            return SimpleNamespace(source_name="测试视频")

        async def execute(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    async def _unexpected_projection_loader(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("cached projection rows should prevent reloading projection entries")

    async def _fake_load_latest_optional_artifact(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        jobs_module,
        "_load_manual_editor_latest_subtitle_projection_entries",
        _unexpected_projection_loader,
    )

    rows = await _load_manual_editor_source_subtitle_dicts(
        _FakeSession(),
        job_id=uuid4(),
        latest_projection_rows=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 2.4,
                "text_raw": "呃， 这个就是M的这个标， 你长按",
                "text_norm": "呃， 这个就是M的这个标， 你长按",
                "text_final": "呃， 这个就是M的这个标， 你长按",
            }
        ],
        latest_projection_data={
            "transcript_layer": "canonical_transcript",
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
        },
    )

    assert [row["text_final"] for row in rows] == ["呃， 这个就是M的这个标， 你长按"]


@pytest.mark.asyncio
async def test_manual_editor_source_subtitles_fallback_does_not_resplit_source_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        async def get(self, model: object, job_id: object) -> SimpleNamespace:
            return SimpleNamespace(source_name="测试视频")

        async def execute(self, *_args: object, **_kwargs: object) -> object:
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    canonical_layer = {
        "alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
        "segments": [
            {
                "index": 0,
                "start": 0.0,
                "end": 12.0,
                "text_raw": "这是一个很长的原始来源字幕，这里只允许展示原始行，不允许在manual editor阶段重新切分。",
                "text_canonical": "这是一个很长的原始来源字幕，这里只允许展示原始行，不允许在manual editor阶段重新切分。",
                "words": [{"word": "这", "start": 0.0, "end": 0.1}],
            }
        ],
    }

    async def _fake_load_latest_optional_artifact(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(data_json=canonical_layer)

    def _unexpected_split(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("manual editor source fallback must not resplit source rows")

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(jobs_module, "_manual_editor_split_long_subtitle_rows", _unexpected_split)

    rows = await _load_manual_editor_source_subtitle_dicts(
        _FakeSession(),
        job_id=uuid4(),
        latest_projection_rows=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 20.0,
                "text_final": "短句",
            }
        ],
        latest_projection_data={
            "transcript_layer": "canonical_transcript",
            "split_profile": {"max_chars": 20, "max_duration": 3.8},
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
        },
    )

    assert [row["text_final"] for row in rows] == [
        "这是一个很长的原始来源字幕，这里只允许展示原始行，不允许在manual editor阶段重新切分。"
    ]
    assert rows[0].get("source_fragment_count") is None


def test_manual_editor_projection_data_requires_current_segmentation_engine_version() -> None:
    assert not _manual_editor_projection_data_is_current({})
    assert not _manual_editor_projection_data_is_current({"segmentation_engine_version": "legacy"})
    assert not _manual_editor_projection_data_is_current(
        {
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": "legacy",
        }
    )
    assert _manual_editor_projection_data_is_current(
        {
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
        }
    )


@pytest.mark.asyncio
async def test_manual_editor_projection_loader_rebuilds_stale_cached_projection_and_refreshes_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.info: dict[str, object] = {}

        def add(self, artifact: object) -> None:
            self.added.append(artifact)

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace | None:
        artifact_types = tuple(kwargs.get("artifact_types") or ())
        if artifact_types == (ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,):
            return SimpleNamespace(
                step_id=uuid4(),
                data_json={
                    "segmentation_engine_version": "legacy",
                    "canonical_alignment_engine_version": "legacy",
                    "transcript_layer": "canonical_transcript",
                    "entries": [
                        {
                            "index": 0,
                            "start": 0.0,
                            "end": 1.0,
                            "text_raw": "旧分句",
                            "text_norm": "旧分句",
                            "text_final": "旧分句",
                        }
                    ],
                },
            )
        return None

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {"segments": [{"index": 0, "start": 0.0, "end": 1.4, "text": "重建分句"}]}

    async def _fake_rebuild_projection_entries(*args: object, **kwargs: object) -> tuple[list[dict[str, object]], dict[str, object]]:
        return (
            [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 1.4,
                    "text_raw": "重建分句",
                    "text_norm": "重建分句",
                    "text_final": "重建分句",
                    "projection_source": "canonical_transcript",
                }
            ],
            {
                "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
                "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
                "canonical_alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
                "transcript_layer": "canonical_transcript",
                "entries": [
                    {
                        "index": 0,
                        "start": 0.0,
                        "end": 1.4,
                        "text_raw": "重建分句",
                        "text_norm": "重建分句",
                        "text_final": "重建分句",
                    }
                ],
            },
        )

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_rebuild_projection_entries_from_canonical_layer",
        _fake_rebuild_projection_entries,
    )

    fake_session = _FakeSession()
    rows, projection_data = await jobs_module._load_manual_editor_latest_subtitle_projection_entries(
        fake_session,
        job_id=job_id,
        fallback_items=None,
    )

    assert [row["text_final"] for row in rows] == ["重建分句"]
    assert [row.get("projection_source") for row in rows] == ["canonical_transcript"]
    assert projection_data["projection_refresh_required"] is True
    assert projection_data["rebuilt_from_canonical_fallback"] is True
    assert not fake_session.added
    assert not fake_session.info


def test_canonical_transcript_data_requires_current_alignment_engine_version() -> None:
    assert not canonical_transcript_data_is_current({})
    assert not canonical_transcript_data_is_current({"alignment_engine_version": "legacy"})
    assert canonical_transcript_data_is_current(
        {"alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION}
    )


def test_manual_editor_projection_contract_locks_current_authoritative_projection() -> None:
    assert _manual_editor_projection_contract_locked(
        manual_projection_items=[],
        raw_projection_rows=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.2,
                "text_final": "当前自动切分",
            }
        ],
        projection_data={
            "transcript_layer": "canonical_transcript",
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
            "canonical_alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
        },
        draft_active=False,
        manual_projection_suspicious=False,
    ) is True


def test_manual_editor_session_model_exposes_projection_diagnostics() -> None:
    session = jobs_module.ManualEditorSessionOut(
        job_id=str(uuid4()),
        timeline_id=str(uuid4()),
        timeline_version=1,
        source_name="demo.mp4",
        source_duration_sec=12.3,
        source_subtitle_basis="canonical_transcript",
        projected_subtitle_basis="canonical_transcript",
        projection_contract_locked=True,
        projection_diagnostics={
            "projection_refresh_required": True,
            "source_projection_fallback_applied": False,
        },
    )

    payload = session.model_dump()
    assert payload["source_subtitle_basis"] == "canonical_transcript"
    assert payload["projected_subtitle_basis"] == "canonical_transcript"
    assert payload["projection_contract_locked"] is True
    assert payload["projection_diagnostics"]["projection_refresh_required"] is True


def test_manual_editor_projection_contract_does_not_lock_subtitle_item_fallback() -> None:
    assert _manual_editor_projection_contract_locked(
        manual_projection_items=[],
        raw_projection_rows=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.2,
                "text_final": "旧字幕条",
            }
        ],
        projection_data={
            "transcript_layer": "subtitle_item",
            "projection_kind": "subtitle_item_baseline",
        },
        draft_active=False,
        manual_projection_suspicious=False,
    ) is False


def test_manual_editor_current_projection_contract_blocks_source_fallback_override() -> None:
    projected = [
        {"index": 0, "start_time": 0.0, "end_time": 1.2, "text_final": "今天我们直奔主题啊"},
    ]
    source_rows = [
        {"index": 0, "start_time": 0.0, "end_time": 0.5, "text_final": "今天"},
        {"index": 1, "start_time": 0.5, "end_time": 1.2, "text_final": "我们直奔主题啊"},
    ]

    assert _manual_editor_should_apply_source_projection_fallback(
        projected_subtitles=projected,
        source_subtitles=source_rows,
        keep_segments=[{"start": 0.0, "end": 1.2}],
        manual_projection_items=[],
        raw_projection_rows=projected,
        projection_data={
            "transcript_layer": "canonical_transcript",
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
            "canonical_alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
        },
        draft_active=False,
        manual_projection_suspicious=False,
    ) is False


def test_resolve_projection_split_profile_ignores_stale_projection_profile() -> None:
    profile = _resolve_projection_split_profile(
        {
            "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
            "split_profile_version": "legacy",
            "split_profile": {"orientation": "landscape", "max_chars": 18, "max_duration": 3.4},
        },
        {"width": 1920, "height": 1080},
    )

    assert profile["orientation"] == "landscape"
    assert profile["max_chars"] == 34
    assert profile["max_duration"] == pytest.approx(5.8)


@pytest.mark.asyncio
async def test_load_latest_subtitle_payloads_rebuilds_stale_projection_from_canonical_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()

    class _FakeResult:
        def scalar_one_or_none(self) -> str:
            return "demo.mp4"

    class _FakeSession:
        async def execute(self, stmt: object) -> _FakeResult:
            return _FakeResult()

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace | None:
        artifact_types = tuple(kwargs.get("artifact_types") or ())
        if artifact_types == ("subtitle_projection_layer",):
            return SimpleNamespace(
                data_json={
                    "segmentation_engine_version": "legacy",
                    "canonical_alignment_engine_version": "legacy",
                    "split_profile": {"max_chars": 30, "max_duration": 5.0},
                    "entries": [
                        {
                            "index": 0,
                            "start": 0.0,
                            "end": 1.0,
                            "text_raw": "旧切分",
                            "text_norm": "旧切分",
                            "text_final": "旧切分",
                        }
                    ],
                }
            )
        if artifact_types == (ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,):
            return SimpleNamespace(
                data_json={
                    "alignment_engine_version": "legacy",
                    "segments": [
                        {
                            "index": 0,
                            "start": 0.0,
                            "end": 1.2,
                            "text_raw": "当前切分",
                            "text_canonical": "当前切分",
                            "words": [
                                {"word": "当前", "start": 0.0, "end": 0.6, "alignment": {}},
                                {"word": "切分", "start": 0.6, "end": 1.2, "alignment": {}},
                            ],
                        }
                    ]
                }
            )
        return None

    async def _fake_load_subtitle_items(*args: object, **kwargs: object) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="旧切分",
                text_norm="旧切分",
                text_final="旧切分",
            )
        ]

    async def _fake_build_canonical_refresh_projection(*args: object, **kwargs: object) -> tuple[SimpleNamespace, dict[str, object], dict[str, object]]:
        layer = SimpleNamespace(
            as_dict=lambda: {
                "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
                "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
                "canonical_alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
                "projection_kind": "canonical_refresh",
                "transcript_layer": "canonical_transcript",
                "split_profile": {"max_chars": 30, "max_duration": 5.0},
                "entries": [
                    {
                        "index": 0,
                        "start": 0.0,
                        "end": 1.2,
                        "text_raw": "当前切分",
                        "text_norm": "当前切分",
                        "text_final": "当前切分",
                    }
                ],
            }
        )
        return layer, {}, {}

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 1.2,
                    "text_raw": "当前切分",
                    "text_canonical": "当前切分",
                    "words": [
                        {"word": "当前", "start": 0.0, "end": 0.6, "alignment": {}},
                        {"word": "切分", "start": 0.6, "end": 1.2, "alignment": {}},
                    ],
                }
            ],
        }

    monkeypatch.setattr("roughcut.pipeline.steps._load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr("roughcut.pipeline.steps._load_subtitle_items", _fake_load_subtitle_items)
    monkeypatch.setattr("roughcut.pipeline.steps._build_canonical_refresh_projection", _fake_build_canonical_refresh_projection)
    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )

    subtitles, projection_data = await _load_latest_subtitle_payloads(
        _FakeSession(),
        job_id=job_id,
    )

    assert [item["text_final"] for item in subtitles] == ["当前切分"]
    assert projection_data["segmentation_engine_version"] == SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION
    assert projection_data["canonical_alignment_engine_version"] == CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION


@pytest.mark.asyncio
async def test_load_latest_subtitle_payloads_rejects_rebuilt_projection_with_output_fallback_alignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()

    class _FakeResult:
        def scalar_one_or_none(self) -> str:
            return "demo.mp4"

    class _FakeSession:
        async def execute(self, stmt: object) -> _FakeResult:
            return _FakeResult()

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace | None:
        artifact_types = tuple(kwargs.get("artifact_types") or ())
        if artifact_types == ("subtitle_projection_layer",):
            return SimpleNamespace(
                data_json={
                    "segmentation_engine_version": "legacy",
                    "canonical_alignment_engine_version": "legacy",
                    "split_profile": {"max_chars": 30, "max_duration": 5.0},
                    "entries": [
                        {
                            "index": 0,
                            "start": 0.0,
                            "end": 1.0,
                            "text_raw": "旧切分",
                            "text_norm": "旧切分",
                            "text_final": "旧切分",
                        }
                    ],
                }
            )
        if artifact_types == (ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,):
            return SimpleNamespace(
                data_json={
                    "alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
                    "segments": [
                        {
                            "index": 0,
                            "start": 0.0,
                            "end": 1.2,
                            "text_raw": "当前切分",
                            "text_canonical": "当前切分",
                            "words": [
                                {
                                    "word": "当前",
                                    "start": 0.0,
                                    "end": 0.6,
                                    "alignment": {"source": "canonical_segment_fallback"},
                                },
                                {
                                    "word": "切分",
                                    "start": 0.6,
                                    "end": 1.2,
                                    "alignment": {"source": "canonical_segment_fallback"},
                                },
                            ],
                        }
                    ],
                }
            )
        return None

    async def _fake_load_subtitle_items(*args: object, **kwargs: object) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="旧切分",
                text_norm="旧切分",
                text_final="旧切分",
            )
        ]

    async def _fake_build_canonical_refresh_projection(*args: object, **kwargs: object) -> tuple[SimpleNamespace, dict[str, object], dict[str, object]]:
        layer = SimpleNamespace(
            as_dict=lambda: {
                "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
                "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
                "canonical_alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
                "projection_kind": "canonical_refresh",
                "transcript_layer": "canonical_transcript",
                "split_profile": {"max_chars": 30, "max_duration": 5.0},
                "entries": [
                    {
                        "index": 0,
                        "start": 0.0,
                        "end": 1.2,
                        "text_raw": "当前切分",
                        "text_norm": "当前切分",
                        "text_final": "当前切分",
                        "words": [
                            {
                                "word": "当前",
                                "start": 0.0,
                                "end": 0.6,
                                "alignment": {"source": "canonical_segment_fallback"},
                            }
                        ],
                    }
                ],
            }
        )
        return layer, {}, {}

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 1.2,
                    "text_raw": "当前切分",
                    "text_canonical": "当前切分",
                    "words": [
                        {
                            "word": "当前",
                            "start": 0.0,
                            "end": 0.6,
                            "alignment": {"source": "canonical_segment_fallback"},
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr("roughcut.pipeline.steps._load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr("roughcut.pipeline.steps._load_subtitle_items", _fake_load_subtitle_items)
    monkeypatch.setattr("roughcut.pipeline.steps._build_canonical_refresh_projection", _fake_build_canonical_refresh_projection)
    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )

    subtitles, projection_data = await _load_latest_subtitle_payloads(
        _FakeSession(),
        job_id=job_id,
    )

    assert [item["text_final"] for item in subtitles] == ["旧切分"]
    assert projection_data["projection_kind"] == "subtitle_item_baseline"
    assert projection_data["transcript_layer"] == "subtitle_item"


@pytest.mark.asyncio
async def test_manual_editor_projection_loader_rebuilds_stale_cached_projection_before_returning_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.info: dict[str, object] = {}

        def add(self, artifact: object) -> None:
            self.added.append(artifact)

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace | None:
        artifact_types = tuple(kwargs.get("artifact_types") or ())
        if artifact_types == (ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,):
            return SimpleNamespace(
                step_id=uuid4(),
                data_json={
                    "segmentation_engine_version": "legacy",
                    "canonical_alignment_engine_version": "legacy",
                    "transcript_layer": "canonical_transcript",
                    "entries": [
                        {
                            "index": 0,
                            "start": 0.0,
                            "end": 1.0,
                            "text_raw": "旧切分",
                            "text_norm": "旧切分",
                            "text_final": "旧切分",
                        }
                    ],
                }
            )
        return None

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {"segments": [{"index": 0, "start": 0.0, "end": 1.4, "text": "重建分句"}]}

    async def _fake_rebuild_projection_entries(*args: object, **kwargs: object) -> tuple[list[dict[str, object]], dict[str, object]]:
        return (
            [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 1.4,
                    "text_raw": "重建分句",
                    "text_norm": "重建分句",
                    "text_final": "重建分句",
                    "projection_source": "canonical_transcript",
                }
            ],
            {
                "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
                "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
                "canonical_alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
                "transcript_layer": "canonical_transcript",
                "entries": [
                    {
                        "index": 0,
                        "start": 0.0,
                        "end": 1.4,
                        "text_raw": "重建分句",
                        "text_norm": "重建分句",
                        "text_final": "重建分句",
                    }
                ],
            },
        )

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_rebuild_projection_entries_from_canonical_layer",
        _fake_rebuild_projection_entries,
    )

    fake_session = _FakeSession()
    rows, projection_data = await jobs_module._load_manual_editor_latest_subtitle_projection_entries(
        fake_session,
        job_id=job_id,
        fallback_items=None,
    )

    assert [row["text_final"] for row in rows] == ["重建分句"]
    assert [row.get("projection_source") for row in rows] == ["canonical_transcript"]
    assert projection_data["projection_refresh_required"] is True
    assert projection_data["rebuilt_from_canonical_fallback"] is True
    assert not fake_session.added
    assert not fake_session.info


@pytest.mark.asyncio
async def test_projection_validation_source_payloads_keep_fact_layers_without_explicit_display_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("canonical transcript path should not query transcript rows")

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "展示层别名不应覆盖显式事实层",
                    "text_raw": "你看到的是EC手电",
                    "text_canonical": "你看到的是EDC手电",
                    "text_final": "",
                    "display_suppressed_reason": "standalone_filler",
                    "words": [],
                }
            ]
        }

    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )

    payloads = await _load_source_subtitle_payloads_for_projection_validation(
        _FakeSession(),
        job_id=uuid4(),
    )

    assert payloads == [
        {
            "index": 0,
            "source_index": 0,
            "source_indexes": [0],
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "你看到的是EC手电",
            "text_norm": "你看到的是EDC手电",
            "transcript_text": "你看到的是EC手电",
            "display_suppressed_reason": "standalone_filler",
            "words": [],
            "projection_source": "canonical_transcript",
        }
    ]


@pytest.mark.asyncio
async def test_projection_validation_source_payloads_preserve_canonical_over_generic_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        async def execute(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("canonical transcript path should not query transcript rows")

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "generic text should not override explicit canonical transcript",
                    "text_raw": "你看到的是EC手电",
                    "text_canonical": "你看到的是EDC手电",
                    "display_suppressed_reason": "standalone_filler",
                    "words": [],
                }
            ]
        }

    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )

    payloads = await _load_source_subtitle_payloads_for_projection_validation(
        _FakeSession(),
        job_id=uuid4(),
    )

    assert payloads == [
        {
            "index": 0,
            "source_index": 0,
            "source_indexes": [0],
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "你看到的是EC手电",
            "text_norm": "你看到的是EDC手电",
            "transcript_text": "你看到的是EC手电",
            "display_suppressed_reason": "standalone_filler",
            "words": [],
            "projection_source": "canonical_transcript",
        }
    ]


@pytest.mark.asyncio
async def test_projection_validation_source_payloads_fallback_to_subtitle_items_keep_source_basis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeTranscriptResult:
        def scalars(self) -> "_FakeTranscriptResult":
            return self

        def all(self) -> list[object]:
            return []

    class _FakeSession:
        async def execute(self, *args: object, **kwargs: object) -> object:
            return _FakeTranscriptResult()

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {}

    async def _fake_load_subtitle_items(*args: object, **kwargs: object) -> list[object]:
        return [
            SimpleNamespace(
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="那个 E C 手电",
                text_norm="EDC手电",
                text_final="",
                display_suppressed_reason="standalone_filler",
            )
        ]

    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )
    monkeypatch.setattr("roughcut.pipeline.steps._load_subtitle_items", _fake_load_subtitle_items)

    payloads = await _load_source_subtitle_payloads_for_projection_validation(
        _FakeSession(),
        job_id=uuid4(),
    )

    assert payloads == [
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "那个 E C 手电",
            "text_norm": "EDC手电",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
            "projection_source": "subtitle_item",
        }
    ]


@pytest.mark.asyncio
async def test_persist_projection_layer_to_subtitle_items_preserves_fact_layers_before_display_surface() -> None:
    class _FakeSession:
        def __init__(self) -> None:
            self.executed: list[object] = []
            self.added: list[object] = []

        async def execute(self, statement: object) -> None:
            self.executed.append(statement)

        def add(self, item: object) -> None:
            self.added.append(item)

        async def flush(self) -> None:
            return None

    session = _FakeSession()
    count = await _persist_projection_layer_to_subtitle_items(
        session,
        job_id=uuid4(),
        refreshed_projection_layer=SimpleNamespace(
            entries=(
                SimpleNamespace(
                    index=0,
                    start=0.0,
                    end=1.0,
                    text_raw="你看到的是EC手电",
                    text_norm="你看到的是EDC手电",
                    text_final=None,
                ),
            )
        ),
    )

    assert count == 1
    assert len(session.added) == 1
    persisted = session.added[0]
    assert persisted.text_raw == "你看到的是EC手电"
    assert persisted.text_norm == "你看到的是EDC手电"
    assert persisted.text_final == "你看到的是EDC手电"


@pytest.mark.asyncio
async def test_manual_editor_latest_subtitle_payloads_preserve_projection_text_without_recleaning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_projection_entries(*args: object, **kwargs: object) -> tuple[list[dict[str, object]], dict[str, object]]:
        return (
            [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 1.5,
                    "text_raw": "你长按它就是一个激光啊，绿激光。",
                    "text_norm": "你长按它就是一个激光啊，绿激光。",
                    "text_final": "你长按它就是一个激光啊，绿激光。",
                }
            ],
            {
                "split_profile": {"max_chars": 20, "max_duration": 3.8},
                "transcript_layer": "canonical_transcript",
            },
        )

    monkeypatch.setattr(
        jobs_module,
        "_load_manual_editor_latest_subtitle_projection_entries",
        _fake_projection_entries,
    )

    rows, _projection_data = await jobs_module._load_manual_editor_latest_subtitle_payloads(
        SimpleNamespace(),
        job_id=uuid4(),
        fallback_to_items=False,
        drop_empty=True,
    )

    assert [row["text_final"] for row in rows] == ["你长按它就是一个激光啊，绿激光。"]


def test_subtitle_projection_layer_persists_projection_words() -> None:
    layer = build_subtitle_projection_layer(
        [
            SimpleNamespace(
                item_index=0,
                start_time=0.0,
                end_time=1.2,
                text_raw="当前切分",
                text_norm="当前切分",
                text_final="当前切分",
                words=[
                    {"word": "当前", "start": 0.0, "end": 0.6, "alignment": {"source": "provider"}},
                    {"word": "切分", "start": 0.6, "end": 1.2, "alignment": {"source": "provider"}},
                ],
            )
        ],
        segmentation_analysis={},
        split_profile={"max_chars": 30, "max_duration": 5.0},
        boundary_refine={},
        quality_report={},
        projection_basis="canonical_local_hybrid",
        transcript_layer="canonical_transcript",
    )

    entries = list(layer.as_dict().get("entries") or [])
    assert len(entries) == 1
    assert [str(word.get("word") or "") for word in list(entries[0].get("words") or [])] == ["当前", "切分"]


def test_manual_editor_projection_entry_payload_preserves_projection_words() -> None:
    payload = jobs_module._manual_editor_subtitle_projection_entry_payload(
        {
            "index": 0,
            "start": 0.0,
            "end": 1.2,
            "text_raw": "当前切分",
            "text_norm": "当前切分",
            "text_final": "当前切分",
            "words": [
                {"word": "当前", "start": 0.0, "end": 0.6, "alignment": {"source": "provider"}},
                {"word": "切分", "start": 0.6, "end": 1.2, "alignment": {"source": "provider"}},
            ],
        }
    )

    assert [str(word.get("word") or "") for word in list(payload.get("words") or [])] == ["当前", "切分"]


def test_manual_editor_canonical_layer_namespace_preserves_projection_rebuild_inputs() -> None:
    canonical_layer = {
        "segments": [
            {
                "index": 0,
                "start": 0.0,
                "end": 5.8,
                "text_canonical": "呃我们其他博主也是也都发过这款手电了",
                "text_raw": "呃我们其他博主也是也都发过这款手电了",
                "words": [
                    {"word": "呃，", "start": 0.0, "end": 0.28, "alignment": {}},
                    {"word": "我们其他博主也是也都发过", "start": 0.28, "end": 3.85, "alignment": {}},
                    {"word": "这款手电了", "start": 3.85, "end": 5.8, "alignment": {}},
                ],
            }
        ]
    }

    namespace = _manual_editor_canonical_layer_namespace(canonical_layer)

    assert str(namespace.source_basis) == "canonical_transcript"
    assert len(tuple(namespace.segments)) == 1
    segment = namespace.segments[0]
    assert str(segment.text_canonical).endswith("这款手电了")
    assert str(segment.text_raw).endswith("这款手电了")
    assert [str(word.word) for word in tuple(segment.words)] == ["呃，", "我们其他博主也是也都发过", "这款手电了"]


def test_manual_editor_canonical_layer_namespace_preserves_explicit_canonical_over_generic_text() -> None:
    namespace = _manual_editor_canonical_layer_namespace(
        {
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "generic text should not override explicit canonical transcript",
                    "text_raw": "你看到的是EC手电",
                    "text_canonical": "你看到的是EDC手电",
                    "text_final": "",
                    "display_suppressed_reason": "standalone_filler",
                    "words": [],
                }
            ]
        }
    )

    segment = namespace.segments[0]
    assert str(segment.text_raw) == "你看到的是EC手电"
    assert str(segment.text_norm) == "你看到的是EDC手电"
    assert str(segment.text_canonical) == "你看到的是EDC手电"
    assert str(segment.text_final) == ""
    assert segment.display_suppressed_reason == "standalone_filler"


def test_projection_assessment_tolerates_small_boundary_reassignment_for_material_tokens() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
    ]
    candidate_items = [
        SimpleNamespace(start_time=0.0, end_time=0.82, text_final="这是"),
        SimpleNamespace(start_time=0.82, end_time=2.0, text_final="EDC17手电参数"),
    ]

    assessment = _build_projection_correction_assessment(
        basis="canonical_local_hybrid",
        reference_items=reference_items,
        candidate_items=candidate_items,
        display_quality_report={"score": 90.0, "metrics": {"subtitle_count": 2}},
    )

    assert assessment["metrics"]["missing_material_token_count"] == 0
    assert assessment["metrics"]["unsupported_material_token_count"] == 0
    assert "projection_unsupported_material_tokens" not in assessment["issue_codes"]


def test_projection_assessment_tolerates_moderate_hybrid_boundary_reassignment_for_material_tokens() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.6, text_final="这一款是1500流明啊。"),
        SimpleNamespace(start_time=1.6, end_time=3.8, text_final="但是它的亮度直接去看。"),
    ]
    candidate_items = [
        SimpleNamespace(start_time=0.0, end_time=3.8, text_final="这一款是1500流明啊，但是它的亮度直接去看。"),
    ]

    assessment = _build_projection_correction_assessment(
        basis="canonical_local_hybrid",
        reference_items=reference_items,
        candidate_items=candidate_items,
        display_quality_report={"score": 92.0, "metrics": {"subtitle_count": 1}},
    )

    assert assessment["metrics"]["missing_material_token_count"] == 0
    assert assessment["metrics"]["unsupported_material_token_count"] == 0
    assert "projection_unsupported_material_tokens" not in assessment["issue_codes"]


def test_projection_boundary_detection_blocks_material_token_split_across_rows() -> None:
    assert _projection_boundary_splits_material_token("另外一把呢就是现在这个奈特", "科尔啊，也是前两个月。")
    assert not _projection_boundary_splits_material_token("另外一把呢就是现在这个", "奈特科尔啊，也是前两个月。")


def test_projection_compact_text_ignores_punctuation_inside_material_tokens() -> None:
    assert _projection_compact_text("奈特。科尔啊，") == "奈特科尔啊"
    assert "奈特科尔" in _projection_compact_text("奈特。\n科尔啊，也是前两个月。")


def test_projection_material_split_entries_are_merged_back_together() -> None:
    merged = _merge_material_split_projection_entries(
        [
            SimpleNamespace(index=0, start=0.0, end=1.0, text_raw="另外一把呢就是现在这个奈特", text_norm="另外一把呢就是现在这个奈特", words=()),
            SimpleNamespace(index=1, start=1.0, end=2.0, text_raw="科尔啊，也是前两个月。", text_norm="科尔啊，也是前两个月。", words=()),
        ]
    )

    assert len(merged) == 1
    assert "奈特科尔" in str(merged[0].text_raw)


def test_projection_material_drift_ignores_punctuation_fragmentation() -> None:
    from roughcut.pipeline.steps import _projection_has_material_content_drift

    assert not _projection_has_material_content_drift(
        baseline_items=[
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="另外一把呢就是现在这个奈特。"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="科尔啊，也是前两个月。"),
        ],
        candidate_items=[
            SimpleNamespace(start_time=0.0, end_time=2.0, text_final="另外一把呢就是现在这个奈特科尔啊，也是前两个月。"),
        ],
    )


def test_projection_material_drift_accepts_numeric_equivalent_tokens() -> None:
    from roughcut.pipeline.steps import _projection_has_material_content_drift

    assert not _projection_has_material_content_drift(
        baseline_items=[
            SimpleNamespace(start_time=0.0, end_time=2.0, text_final="它是一千五百流明啊。"),
        ],
        candidate_items=[
            SimpleNamespace(start_time=0.0, end_time=2.0, text_final="它是1500流明啊。"),
        ],
    )


def test_projection_candidate_selection_prefers_higher_quality_hybrid_when_content_is_preserved() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
    ]
    canonical_candidate = {
        "basis": "canonical_refresh",
        "transcript_layer": "canonical_transcript",
        "items": [
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="17手电参数"),
        ],
        "quality_report": {"score": 85.0, "metrics": {"subtitle_count": 2}},
    }
    hybrid_candidate = {
        "basis": "canonical_local_hybrid",
        "transcript_layer": "canonical_transcript",
        "items": [
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
        ],
        "quality_report": {"score": 90.0, "metrics": {"subtitle_count": 2}},
    }

    selected, report = _select_projection_candidate(
        candidates=[canonical_candidate, hybrid_candidate],
        reference_items=reference_items,
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        preferred_basis="canonical_display_boundary_hybrid",
    )

    assert selected["basis"] == "canonical_refresh"
    assert report["selected_projection_basis"] == "canonical_refresh"


def test_merge_short_display_boundary_entries_prefers_canonical_surface_over_raw_text() -> None:
    entries = [
        SimpleNamespace(index=0, start=0.0, end=0.4, text_raw="EC", text_norm="EDC", words=()),
        SimpleNamespace(index=1, start=0.41, end=1.2, text_raw="手电", text_norm="手电", words=()),
    ]

    merged = _merge_short_display_boundary_entries(entries, max_chars=30)

    assert len(merged) == 1
    assert merged[0].text_raw == "EDC手电"
    assert merged[0].text_norm == "EDC手电"


def test_build_projection_items_from_entries_preserves_canonical_surface_separately_from_display() -> None:
    items = _build_projection_items_from_entries(
        [
            SimpleNamespace(
                index=0,
                start=0.0,
                end=1.0,
                text_raw="你看到的是EDC手电",
                text_norm="EDC",
                words=(),
            )
        ]
    )

    assert len(items) == 1
    assert items[0].text_raw == "你看到的是EDC手电"
    assert items[0].text_norm == "EDC"
    assert items[0].text_final == "你看到的是EDC手电"


def test_build_projection_entries_from_subtitle_items_preserves_canonical_surface_when_using_display_text() -> None:
    entries = _build_projection_entries_from_subtitle_items(
        [
            SimpleNamespace(
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="那个 E C 手电",
                text_norm="EDC手电",
                text_final="这个手电",
            )
        ],
        use_final_text=True,
    )

    assert len(entries) == 1
    assert entries[0].text_raw == "这个手电"
    assert entries[0].text_norm == "EDC手电"


def test_canonical_transcript_layer_namespace_preserves_explicit_display_and_canonical_surfaces() -> None:
    layer = _canonical_transcript_layer_namespace(
        {
            "segments": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text": "generic text should not override explicit surfaces",
                    "text_raw": "那个 E C 手电",
                    "text_canonical": "EDC手电",
                    "text_final": "",
                    "display_suppressed_reason": "standalone_filler",
                }
            ]
        }
    )

    assert len(layer.segments) == 1
    assert layer.segments[0].text_raw == "那个 E C 手电"
    assert layer.segments[0].text_norm == "EDC手电"
    assert layer.segments[0].text_canonical == "EDC手电"
    assert layer.segments[0].text_final == ""
    assert layer.segments[0].display_suppressed_reason == "standalone_filler"


def test_projection_candidate_selection_prefers_higher_scored_hybrid_despite_slightly_higher_low_confidence_windows() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
    ]
    canonical_candidate = {
        "basis": "canonical_refresh",
        "transcript_layer": "canonical_transcript",
        "items": reference_items,
        "quality_report": {"score": 95.5, "metrics": {"subtitle_count": 2}},
        "analysis": {
            "fragment_start_count": 2,
            "fragment_end_count": 10,
            "suspicious_boundary_count": 19,
            "low_confidence_window_count": 29,
        },
    }
    hybrid_candidate = {
        "basis": "canonical_local_hybrid",
        "transcript_layer": "canonical_transcript",
        "items": reference_items,
        "quality_report": {"score": 100.0, "metrics": {"subtitle_count": 2}},
        "analysis": {
            "fragment_start_count": 2,
            "fragment_end_count": 8,
            "suspicious_boundary_count": 14,
            "low_confidence_window_count": 32,
        },
    }

    selected, report = _select_projection_candidate(
        candidates=[canonical_candidate, hybrid_candidate],
        reference_items=reference_items,
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        preferred_basis="canonical_display_boundary_hybrid",
    )

    assert selected["basis"] == "canonical_refresh"
    assert report["selected_projection_basis"] == "canonical_refresh"


def test_local_hybrid_projection_entries_now_pass_through_canonical_boundaries() -> None:
    entries = [
        SimpleNamespace(index=0, start=0.0, end=1.6, text_raw="需要的，所以说那也就没啥好说的了。", text_norm="需要的，所以说那也就没啥好说的了。", words=()),
        SimpleNamespace(index=1, start=1.61, end=2.03, text_raw="该升级。呃", text_norm="该升级。呃", words=()),
        SimpleNamespace(index=2, start=2.04, end=3.84, text_raw="我们其他博主也是也都发过这款手电了，我们。", text_norm="我们其他博主也是也都发过这款手电了，我们。", words=()),
        SimpleNamespace(index=3, start=3.9, end=4.8, text_raw="就简单的做一下展示。", text_norm="就简单的做一下展示。", words=()),
    ]

    refined = _build_local_hybrid_projection_entries(entries, split_profile={"max_chars": 30, "max_duration": 5.0})
    texts = [str(entry.text_raw) for entry in refined]

    assert texts == [str(entry.text_raw) for entry in entries]


def test_local_hybrid_projection_entries_do_not_merge_followon_clause() -> None:
    entries = [
        SimpleNamespace(index=0, start=0.0, end=1.2, text_raw="这个晚上出门都会带它", text_norm="这个晚上出门都会带它", words=()),
        SimpleNamespace(index=1, start=1.21, end=1.59, text_raw="很实用", text_norm="很实用", words=()),
        SimpleNamespace(index=2, start=1.60, end=2.8, text_raw="而且它的这个UV的功能啊", text_norm="而且它的这个UV的功能啊", words=()),
        SimpleNamespace(index=3, start=2.82, end=3.72, text_raw="也不是说只限用照明", text_norm="也不是说只限用照明", words=()),
    ]

    refined = _build_local_hybrid_projection_entries(entries, split_profile={"max_chars": 30, "max_duration": 5.0})
    texts = [str(entry.text_raw) for entry in refined]

    assert texts == [str(entry.text_raw) for entry in entries]


def test_local_hybrid_projection_entries_keep_overfull_rows_for_segmentation_stage() -> None:
    entries = [
        SimpleNamespace(index=0, start=0.0, end=1.2, text_raw="这个晚上出门都会带它", text_norm="这个晚上出门都会带它", words=()),
        SimpleNamespace(index=1, start=1.21, end=1.59, text_raw="很实用", text_norm="很实用", words=()),
        SimpleNamespace(index=2, start=1.60, end=2.8, text_raw="而且它的这个UV的功能啊", text_norm="而且它的这个UV的功能啊", words=()),
        SimpleNamespace(index=3, start=2.82, end=3.72, text_raw="也不是说只限用照明", text_norm="也不是说只限用照明", words=()),
    ]

    refined = _build_local_hybrid_projection_entries(entries, split_profile={"max_chars": 18, "max_duration": 3.4})
    texts = [str(entry.text_raw) for entry in refined]

    assert texts == [str(entry.text_raw) for entry in entries]


def test_local_hybrid_projection_entries_do_not_reassign_short_residual_rightward() -> None:
    entries = [
        SimpleNamespace(index=0, start=0.0, end=1.6, text_raw="需要的，所以说那也就没啥好说的了。", text_norm="需要的，所以说那也就没啥好说的了。", words=()),
        SimpleNamespace(index=1, start=1.61, end=2.03, text_raw="该升级。呃", text_norm="该升级。呃", words=()),
        SimpleNamespace(index=2, start=2.04, end=3.84, text_raw="我们其他博主也是也都发过这款手电了，我们。", text_norm="我们其他博主也是也都发过这款手电了，我们。", words=()),
        SimpleNamespace(index=3, start=3.9, end=4.8, text_raw="就简单的做一下展示。", text_norm="就简单的做一下展示。", words=()),
    ]

    refined = _build_local_hybrid_projection_entries(entries, split_profile={"max_chars": 18, "max_duration": 3.4})
    texts = [str(entry.text_raw) for entry in refined]

    assert texts == [str(entry.text_raw) for entry in entries]


def test_local_hybrid_projection_entries_do_not_resegment_reason_preamble() -> None:
    entries = [
        SimpleNamespace(index=0, start=0.0, end=1.1, text_raw="所以说它的揣在兜里非常轻便非常的无感", text_norm="所以说它的揣在兜里非常轻便非常的无感", words=()),
        SimpleNamespace(index=1, start=1.11, end=2.35, text_raw="所以说为什么我平时比如临时出个门", text_norm="所以说为什么我平时比如临时出个门", words=()),
        SimpleNamespace(index=2, start=2.36, end=3.72, text_raw="遛个狗啊或者说简单的这个短途的通勤", text_norm="遛个狗啊或者说简单的这个短途的通勤", words=()),
        SimpleNamespace(index=3, start=3.73, end=4.85, text_raw="这个晚上出门都会带它", text_norm="这个晚上出门都会带它", words=()),
        SimpleNamespace(index=4, start=4.86, end=5.46, text_raw="很实用而且它的这个UV的功能", text_norm="很实用而且它的这个UV的功能", words=()),
        SimpleNamespace(index=5, start=5.47, end=6.24, text_raw="也不是说只限用照明", text_norm="也不是说只限用照明", words=()),
    ]

    refined = _build_local_hybrid_projection_entries(entries, split_profile={"max_chars": 20, "max_duration": 3.8})
    texts = [str(entry.text_raw) for entry in refined]

    assert texts == [str(entry.text_raw) for entry in entries]


def test_projection_candidate_selection_prefers_refresh_when_hybrid_is_more_fragmentary() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="所以说为什么我平时"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="比如临时出个门遛个狗啊"),
    ]
    canonical_candidate = {
        "basis": "canonical_refresh",
        "transcript_layer": "canonical_transcript",
        "items": [
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="所以说为什么我平时"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="比如临时出个门遛个狗啊"),
        ],
        "analysis": {
            "fragment_start_count": 0,
            "fragment_end_count": 0,
            "suspicious_boundary_count": 0,
            "low_confidence_window_count": 0,
        },
        "quality_report": {"score": 92.0, "metrics": {"subtitle_count": 2}},
    }
    hybrid_candidate = {
        "basis": "canonical_local_hybrid",
        "transcript_layer": "canonical_transcript",
        "items": [
            SimpleNamespace(start_time=0.0, end_time=2.0, text_final="所以说为什么我平时比如临时出个门遛个狗啊"),
        ],
        "analysis": {
            "fragment_start_count": 1,
            "fragment_end_count": 1,
            "suspicious_boundary_count": 1,
            "low_confidence_window_count": 1,
        },
        "quality_report": {"score": 94.0, "metrics": {"subtitle_count": 1}},
    }

    selected, report = _select_projection_candidate(
        candidates=[canonical_candidate, hybrid_candidate],
        reference_items=reference_items,
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        preferred_basis="canonical_display_boundary_hybrid",
    )

    assert selected["basis"] == "canonical_refresh"
    assert report["selected_projection_basis"] == "canonical_refresh"


def test_projection_candidate_selection_tolerates_additive_numeric_material_token_merge() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=0.8, text_final="这都画的呢，呃，1000。"),
        SimpleNamespace(start_time=0.8, end_time=1.6, text_final="500毫安的内置。"),
    ]
    canonical_candidate = {
        "basis": "canonical_refresh",
        "transcript_layer": "canonical_transcript",
        "items": reference_items,
        "quality_report": {"score": 95.5, "metrics": {"subtitle_count": 2}},
    }
    hybrid_candidate = {
        "basis": "canonical_local_hybrid",
        "transcript_layer": "canonical_transcript",
        "items": [
            SimpleNamespace(
                start_time=0.0,
                end_time=1.6,
                text_final="这都画的呢，呃，1500毫安的内置。",
            )
        ],
        "quality_report": {"score": 98.5, "metrics": {"subtitle_count": 1}},
    }

    pool = _build_projection_candidate_pool(
        canonical_projection_items=canonical_candidate["items"],
        projection_analysis=SimpleNamespace(),
        canonical_quality_report=canonical_candidate["quality_report"],
        hybrid_projection_items=hybrid_candidate["items"],
        hybrid_projection_analysis=SimpleNamespace(),
        hybrid_quality_report=hybrid_candidate["quality_report"],
        existing_projection_items=[],
        existing_projection_analysis=SimpleNamespace(),
        existing_quality_report={},
    )

    assert [candidate["basis"] for candidate in pool] == ["canonical_refresh"]


def test_projection_candidate_pool_excludes_hybrid_that_resegments_canonical_boundaries() -> None:
    pool = _build_projection_candidate_pool(
        canonical_projection_items=[
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
        ],
        projection_analysis=SimpleNamespace(),
        canonical_quality_report={"score": 90.0},
        hybrid_projection_items=[
            SimpleNamespace(start_time=0.0, end_time=2.0, text_final="这是EDC17手电参数"),
        ],
        hybrid_projection_analysis=SimpleNamespace(),
        hybrid_quality_report={"score": 96.0},
        existing_projection_items=[],
        existing_projection_analysis=SimpleNamespace(),
        existing_quality_report={},
    )

    assert [candidate["basis"] for candidate in pool] == ["canonical_refresh"]


def test_projection_candidate_pool_allows_higher_quality_hybrid_with_moderate_shape_drift() -> None:
    canonical_items = [
        SimpleNamespace(start_time=float(index), end_time=float(index + 1), text_final=f"第{index}行字幕")
        for index in range(20)
    ]
    hybrid_items = [
        SimpleNamespace(start_time=0.0, end_time=2.0, text_final="第0行字幕第1行字幕"),
        *[
            SimpleNamespace(start_time=float(index), end_time=float(index + 1), text_final=f"第{index}行字幕")
            for index in range(2, 18)
        ],
        SimpleNamespace(start_time=18.0, end_time=20.0, text_final="第18行字幕第19行字幕"),
    ]

    pool = _build_projection_candidate_pool(
        canonical_projection_items=canonical_items,
        projection_analysis=SimpleNamespace(),
        canonical_quality_report={"score": 90.0, "metrics": {"subtitle_count": len(canonical_items)}},
        hybrid_projection_items=hybrid_items,
        hybrid_projection_analysis=SimpleNamespace(),
        hybrid_quality_report={"score": 96.0, "metrics": {"subtitle_count": len(hybrid_items)}},
        existing_projection_items=[],
        existing_projection_analysis=SimpleNamespace(),
        existing_quality_report={},
    )

    assert [candidate["basis"] for candidate in pool] == ["canonical_refresh"]


def test_projection_candidate_pool_keeps_canonical_as_single_segmentation_authority() -> None:
    pool = _build_projection_candidate_pool(
        canonical_projection_items=[SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17")],
        projection_analysis=SimpleNamespace(),
        canonical_quality_report={"score": 85.0},
        hybrid_projection_items=[SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17")],
        hybrid_projection_analysis=SimpleNamespace(),
        hybrid_quality_report={"score": 90.0},
        existing_projection_items=[SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是")],
        existing_projection_analysis=SimpleNamespace(),
        existing_quality_report={"score": 95.0},
    )

    assert [candidate["basis"] for candidate in pool] == ["canonical_refresh"]


def test_projection_candidate_pool_allows_display_boundary_hybrid_when_it_improves_quality_without_material_drift() -> None:
    canonical_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="17手电参数"),
    ]
    hybrid_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
    ]

    pool = _build_projection_candidate_pool(
        canonical_projection_items=canonical_items,
        projection_analysis=SimpleNamespace(),
        canonical_quality_report={
            "score": 89.0,
            "warning_reasons": ["普通词跨字幕截断 1 处"],
            "metrics": {"subtitle_count": 2, "generic_word_split_count": 1},
        },
        hybrid_projection_items=hybrid_items,
        hybrid_projection_analysis=SimpleNamespace(),
        hybrid_quality_report={
            "score": 88.0,
            "warning_reasons": [],
            "metrics": {"subtitle_count": 2, "generic_word_split_count": 0},
        },
        existing_projection_items=[],
        existing_projection_analysis=SimpleNamespace(),
        existing_quality_report={},
    )

    assert [candidate["basis"] for candidate in pool] == [
        "canonical_refresh",
        "canonical_display_boundary_hybrid",
    ]


def test_projection_candidate_pool_allows_display_baseline_when_quality_guard_requests_it() -> None:
    pool = _build_projection_candidate_pool(
        canonical_projection_items=[SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17")],
        projection_analysis=SimpleNamespace(),
        canonical_quality_report={"score": 85.0},
        hybrid_projection_items=[],
        hybrid_projection_analysis=SimpleNamespace(),
        hybrid_quality_report={},
        existing_projection_items=[SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17")],
        existing_projection_analysis=SimpleNamespace(),
        existing_quality_report={"score": 95.0},
        allow_display_baseline_preserved=True,
    )

    assert [candidate["basis"] for candidate in pool] == [
        "canonical_refresh",
        "display_baseline_preserved",
    ]


def test_projection_candidate_pool_excludes_canonical_refresh_when_output_fallback_is_detected() -> None:
    pool = _build_projection_candidate_pool(
        canonical_projection_items=[
            SimpleNamespace(
                start_time=0.0,
                end_time=1.0,
                text_final="这是EDC17",
                words=(
                    {"word": "这是", "start": 0.0, "end": 0.5, "alignment": {"source": "postprocess_text_fallback"}},
                ),
            )
        ],
        projection_analysis=SimpleNamespace(),
        canonical_quality_report={
            "score": 85.0,
            "metrics": {
                "subtitle_count": 1,
                "alignment_source": {"source_counts": {"fallback": 1}},
            },
        },
        hybrid_projection_items=[],
        hybrid_projection_analysis=SimpleNamespace(),
        hybrid_quality_report={},
        existing_projection_items=[SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17")],
        existing_projection_analysis=SimpleNamespace(),
        existing_quality_report={"score": 95.0},
        allow_display_baseline_preserved=True,
        suppress_canonical_refresh=True,
    )

    assert [candidate["basis"] for candidate in pool] == [
        "display_baseline_preserved",
    ]


@pytest.mark.asyncio
async def test_build_canonical_refresh_projection_does_not_opt_into_display_baseline_guard_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_entry = SimpleNamespace(index=0, start=0.0, end=1.0, text_raw="旧分句", text_norm="旧分句", words=())
    canonical_entry = SimpleNamespace(index=0, start=0.0, end=1.2, text_raw="新分句", text_norm="新分句", words=())
    captured: dict[str, object] = {}

    class _FakeProjectionLayer:
        def __init__(self, items: list[SimpleNamespace], *, transcript_layer: str, split_profile: dict[str, object]) -> None:
            self.entries = tuple(items)
            self.transcript_layer = transcript_layer
            self.split_profile = dict(split_profile)

        def as_dict(self) -> dict[str, object]:
            return {
                "entries": [
                    {
                        "index": int(getattr(item, "index", 0) or 0),
                        "start": float(getattr(item, "start_time", getattr(item, "start", 0.0)) or 0.0),
                        "end": float(getattr(item, "end_time", getattr(item, "end", 0.0)) or 0.0),
                        "text_raw": str(getattr(item, "text_raw", getattr(item, "text_final", "")) or ""),
                    }
                    for item in self.entries
                ],
                "transcript_layer": self.transcript_layer,
                "split_profile": dict(self.split_profile),
            }

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace | None:
        artifact_types = tuple(kwargs.get("artifact_types") or ())
        if artifact_types == ("media_meta",):
            return SimpleNamespace(data_json={"width": 1920, "height": 1080})
        return None

    def _fake_projection_items(entries: list[SimpleNamespace]) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                start_time=float(getattr(entry, "start", 0.0) or 0.0),
                end_time=float(getattr(entry, "end", 0.0) or 0.0),
                text_final=str(getattr(entry, "text_raw", "") or ""),
            )
            for entry in entries
        ]

    monkeypatch.setattr(pipeline_steps_module, "subtitle_projection_data_is_current", lambda _payload: False)
    monkeypatch.setattr(pipeline_steps_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_projection_entries_from_subtitle_items",
        lambda *args, **kwargs: [existing_entry],
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_projection_items_from_entries",
        _fake_projection_items,
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "build_subtitle_quality_report_from_items",
        lambda **kwargs: {
            "score": 95.0,
            "warning_reasons": [],
            "metrics": {"subtitle_count": len(list(kwargs.get("subtitle_items") or []))},
        },
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "analyze_subtitle_segmentation",
        lambda entries: SimpleNamespace(
            fragment_start_count=0,
            fragment_end_count=0,
            suspicious_boundary_count=0,
            low_confidence_window_count=0,
        ),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_segmentation_segments_from_canonical_layer",
        lambda _layer: [SimpleNamespace()],
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "segment_subtitles",
        lambda *args, **kwargs: SimpleNamespace(
            entries=[canonical_entry],
            analysis=SimpleNamespace(
                fragment_start_count=0,
                fragment_end_count=0,
                suspicious_boundary_count=0,
                low_confidence_window_count=0,
            ),
        ),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_display_boundary_hybrid_projection_entries",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_display_boundary_hybrid_candidate_worth_adding",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_should_keep_existing_subtitle_projection",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("display baseline guard should stay disabled unless a caller explicitly opts in")
        ),
    )

    def _fake_build_projection_candidate_pool(*, allow_display_baseline_preserved: bool = False, **kwargs: object) -> list[dict[str, object]]:
        captured["allow_display_baseline_preserved"] = allow_display_baseline_preserved
        return [
            {
                "basis": "canonical_refresh",
                "transcript_layer": "canonical_transcript",
                "items": [SimpleNamespace(index=0, start_time=0.0, end_time=1.2, text_raw="新分句", text_final="新分句")],
                "analysis": SimpleNamespace(
                    fragment_start_count=0,
                    fragment_end_count=0,
                    suspicious_boundary_count=0,
                    low_confidence_window_count=0,
                ),
                "quality_report": {
                    "score": 90.0,
                    "warning_reasons": [],
                    "metrics": {"subtitle_count": 1},
                },
            }
        ]

    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_projection_candidate_pool",
        _fake_build_projection_candidate_pool,
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_select_projection_candidate",
        lambda **kwargs: (
            list(kwargs.get("candidates") or [])[0],
            {"selected_basis": "canonical_refresh", "selection_policy": "canonical_transcript_is_single_projection_authority"},
        ),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "build_subtitle_projection_layer",
        lambda items, **kwargs: _FakeProjectionLayer(
            list(items),
            transcript_layer=str(kwargs.get("transcript_layer") or ""),
            split_profile=dict(kwargs.get("split_profile") or {}),
        ),
    )

    refreshed_projection_layer, _quality_report, correction_score_report = await pipeline_steps_module._build_canonical_refresh_projection(
        None,
        job_id=uuid4(),
        source_name="demo.mp4",
        subtitle_items=[],
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        projection_data={},
    )

    assert captured["allow_display_baseline_preserved"] is False
    assert refreshed_projection_layer.transcript_layer == "canonical_transcript"
    assert correction_score_report["selected_basis"] == "canonical_refresh"


@pytest.mark.asyncio
async def test_build_canonical_refresh_projection_forces_display_baseline_when_canonical_output_fallback_is_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_words = ({"text": "旧分句", "start": 0.0, "end": 1.0, "source": "provider"},)
    existing_entry = SimpleNamespace(
        index=0,
        start=0.0,
        end=1.0,
        text_raw="旧分句",
        text_norm="旧分句",
        words=existing_words,
    )
    canonical_entry = SimpleNamespace(index=0, start=0.0, end=1.2, text_raw="新分句", text_norm="新分句", words=())
    captured: dict[str, object] = {}

    class _FakeProjectionLayer:
        def __init__(self, items: list[SimpleNamespace], *, transcript_layer: str, split_profile: dict[str, object]) -> None:
            self.entries = tuple(items)
            self.transcript_layer = transcript_layer
            self.split_profile = dict(split_profile)

        def as_dict(self) -> dict[str, object]:
            return {
                "entries": [
                    {
                        "index": int(getattr(item, "index", 0) or 0),
                        "start": float(getattr(item, "start_time", getattr(item, "start", 0.0)) or 0.0),
                        "end": float(getattr(item, "end_time", getattr(item, "end", 0.0)) or 0.0),
                        "text_raw": str(getattr(item, "text_raw", getattr(item, "text_final", "")) or ""),
                    }
                    for item in self.entries
                ],
                "transcript_layer": self.transcript_layer,
                "split_profile": dict(self.split_profile),
            }

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace | None:
        artifact_types = tuple(kwargs.get("artifact_types") or ())
        if artifact_types == ("media_meta",):
            return SimpleNamespace(data_json={"width": 1920, "height": 1080})
        return None

    def _fake_projection_items(entries: list[SimpleNamespace]) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                start_time=float(getattr(entry, "start", 0.0) or 0.0),
                end_time=float(getattr(entry, "end", 0.0) or 0.0),
                text_final=str(getattr(entry, "text_raw", "") or ""),
                words=tuple(getattr(entry, "words", ()) or ()),
            )
            for entry in entries
        ]

    monkeypatch.setattr(pipeline_steps_module, "subtitle_projection_data_is_current", lambda _payload: False)
    monkeypatch.setattr(pipeline_steps_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_projection_entries_from_subtitle_items",
        lambda *args, **kwargs: [existing_entry],
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_projection_items_from_entries",
        _fake_projection_items,
    )

    def _fake_quality_report_from_items(**kwargs: object) -> dict[str, object]:
        subtitle_items = list(kwargs.get("subtitle_items") or [])
        if subtitle_items and str(getattr(subtitle_items[0], "text_final", "") or "") == "新分句":
            return {
                "score": 72.0,
                "warning_reasons": [],
                "metrics": {
                    "subtitle_count": 1,
                    "alignment_source": {"source_counts": {"fallback": 1}},
                },
            }
        return {
            "score": 95.0,
            "warning_reasons": [],
            "metrics": {
                "subtitle_count": len(subtitle_items),
                "alignment_source": {
                    "word_count": len(existing_words),
                    "missing_word_subtitle_count": 0,
                    "per_subtitle": [{"index": 0, "dominant_source": "provider"}],
                },
            },
        }

    monkeypatch.setattr(
        pipeline_steps_module,
        "build_subtitle_quality_report_from_items",
        _fake_quality_report_from_items,
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "analyze_subtitle_segmentation",
        lambda entries: SimpleNamespace(
            fragment_start_count=0,
            fragment_end_count=0,
            suspicious_boundary_count=0,
            low_confidence_window_count=0,
        ),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_segmentation_segments_from_canonical_layer",
        lambda _layer: [SimpleNamespace()],
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "segment_subtitles",
        lambda *args, **kwargs: SimpleNamespace(
            entries=[canonical_entry],
            analysis=SimpleNamespace(
                fragment_start_count=0,
                fragment_end_count=0,
                suspicious_boundary_count=0,
                low_confidence_window_count=0,
            ),
        ),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_display_boundary_hybrid_projection_entries",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_display_boundary_hybrid_candidate_worth_adding",
        lambda **kwargs: False,
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_should_keep_existing_subtitle_projection",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("output fallback guard should bypass legacy quality-guard fallback arbitration")
        ),
    )

    def _fake_build_projection_candidate_pool(*, allow_display_baseline_preserved: bool = False, suppress_canonical_refresh: bool = False, **kwargs: object) -> list[dict[str, object]]:
        captured["allow_display_baseline_preserved"] = allow_display_baseline_preserved
        captured["suppress_canonical_refresh"] = suppress_canonical_refresh
        return [
            {
                "basis": "display_baseline_preserved",
                "transcript_layer": "subtitle_item",
                "items": [
                    SimpleNamespace(
                        index=0,
                        start_time=0.0,
                        end_time=1.0,
                        text_raw="旧分句",
                        text_final="旧分句",
                        words=existing_words,
                    )
                ],
                "analysis": SimpleNamespace(
                    fragment_start_count=0,
                    fragment_end_count=0,
                    suspicious_boundary_count=0,
                    low_confidence_window_count=0,
                ),
                "quality_report": {
                    "score": 95.0,
                    "warning_reasons": [],
                    "metrics": {
                        "subtitle_count": 1,
                        "alignment_source": {
                            "word_count": len(existing_words),
                            "missing_word_subtitle_count": 0,
                            "per_subtitle": [{"index": 0, "dominant_source": "provider"}],
                        },
                    },
                },
            }
        ]

    monkeypatch.setattr(
        pipeline_steps_module,
        "_build_projection_candidate_pool",
        _fake_build_projection_candidate_pool,
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "_select_projection_candidate",
        lambda **kwargs: (
            list(kwargs.get("candidates") or [])[0],
            {"selected_basis": "display_baseline_preserved"},
        ),
    )
    monkeypatch.setattr(
        pipeline_steps_module,
        "build_subtitle_projection_layer",
        lambda items, **kwargs: _FakeProjectionLayer(
            list(items),
            transcript_layer=str(kwargs.get("transcript_layer") or ""),
            split_profile=dict(kwargs.get("split_profile") or {}),
        ),
    )

    refreshed_projection_layer, _quality_report, correction_score_report = await pipeline_steps_module._build_canonical_refresh_projection(
        None,
        job_id=uuid4(),
        source_name="demo.mp4",
        subtitle_items=[],
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        projection_data={},
    )

    assert captured["allow_display_baseline_preserved"] is True
    assert captured["suppress_canonical_refresh"] is True
    assert refreshed_projection_layer.transcript_layer == "subtitle_item"
    assert correction_score_report["selected_basis"] == "display_baseline_preserved"
    assert correction_score_report["output_fallback_guard_applied"] is True
    assert correction_score_report["selection_policy"] == "display_baseline_preserved_for_output_fallback_guard"


def test_projection_candidate_selection_can_keep_display_baseline_when_quality_guard_allows_it() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
    ]
    canonical_candidate = {
        "basis": "canonical_refresh",
        "transcript_layer": "canonical_transcript",
        "items": [
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="17手电参数"),
        ],
        "quality_report": {
            "score": 85.0,
            "warning_reasons": ["split token"],
            "metrics": {
                "subtitle_count": 2,
                "short_fragment_count": 1,
                "generic_word_split_count": 1,
            },
        },
    }
    baseline_candidate = {
        "basis": "display_baseline_preserved",
        "transcript_layer": "subtitle_item",
        "items": reference_items,
        "quality_report": {
            "score": 95.0,
            "warning_reasons": [],
            "metrics": {
                "subtitle_count": 2,
                "short_fragment_count": 0,
                "generic_word_split_count": 0,
            },
        },
    }

    selected, report = _select_projection_candidate(
        candidates=[canonical_candidate, baseline_candidate],
        reference_items=reference_items,
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        preferred_basis="display_baseline_preserved",
    )

    assert selected["basis"] == "display_baseline_preserved"
    assert report["selected_projection_basis"] == "display_baseline_preserved"


def test_projection_candidate_selection_can_prefer_display_boundary_hybrid_over_split_refresh() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
        SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
    ]
    canonical_candidate = {
        "basis": "canonical_refresh",
        "transcript_layer": "canonical_transcript",
        "items": [
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="17手电参数"),
        ],
        "quality_report": {
            "score": 89.0,
            "warning_reasons": ["普通词跨字幕截断 1 处"],
            "metrics": {"subtitle_count": 2, "generic_word_split_count": 1},
        },
        "analysis": {
            "fragment_start_count": 0,
            "fragment_end_count": 0,
            "suspicious_boundary_count": 0,
            "low_confidence_window_count": 0,
        },
    }
    hybrid_candidate = {
        "basis": "canonical_display_boundary_hybrid",
        "transcript_layer": "canonical_transcript",
        "items": reference_items,
        "quality_report": {
            "score": 88.0,
            "warning_reasons": [],
            "metrics": {"subtitle_count": 2, "generic_word_split_count": 0},
        },
        "analysis": {
            "fragment_start_count": 0,
            "fragment_end_count": 0,
            "suspicious_boundary_count": 0,
            "low_confidence_window_count": 0,
        },
    }

    selected, report = _select_projection_candidate(
        candidates=[canonical_candidate, hybrid_candidate],
        reference_items=reference_items,
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        preferred_basis="canonical_display_boundary_hybrid",
    )

    assert selected["basis"] == "canonical_display_boundary_hybrid"
    assert report["selected_projection_basis"] == "canonical_display_boundary_hybrid"


def test_projection_candidate_selection_prefers_display_baseline_on_tie_when_quality_guard_requests_it() -> None:
    reference_items = [
        SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
    ]
    canonical_candidate = {
        "basis": "canonical_refresh",
        "transcript_layer": "canonical_transcript",
        "items": reference_items,
        "quality_report": {
            "score": 95.0,
            "warning_reasons": [],
            "metrics": {"subtitle_count": 1},
        },
    }
    baseline_candidate = {
        "basis": "display_baseline_preserved",
        "transcript_layer": "subtitle_item",
        "items": reference_items,
        "quality_report": {
            "score": 95.0,
            "warning_reasons": [],
            "metrics": {"subtitle_count": 1},
        },
    }

    selected, report = _select_projection_candidate(
        candidates=[canonical_candidate, baseline_candidate],
        reference_items=reference_items,
        canonical_transcript_layer=SimpleNamespace(correction_metrics={}),
        preferred_basis="display_baseline_preserved",
    )

    assert selected["basis"] == "display_baseline_preserved"
    assert report["selected_projection_basis"] == "display_baseline_preserved"


def test_projection_selection_policy_marks_quality_guard_baseline_preserve() -> None:
    assert (
        _projection_selection_policy(
            selected_basis="display_baseline_preserved",
            canonical_projection_items=[SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17")],
            keep_existing_projection=True,
        )
        == "display_baseline_preserved_for_quality_guard"
    )


def test_should_keep_existing_projection_rejects_material_content_drift() -> None:
    assert not _should_keep_existing_subtitle_projection(
        existing_quality_report={
            "score": 100.0,
            "blocking": False,
            "warning_reasons": [],
            "metrics": {"subtitle_count": 2},
        },
        refreshed_quality_report={
            "score": 90.0,
            "blocking": False,
            "warning_reasons": ["short fragments"],
            "metrics": {"subtitle_count": 2},
        },
        canonical_transcript_layer=SimpleNamespace(
            correction_metrics={"accepted_correction_count": 0, "pending_correction_count": 0},
        ),
        existing_projection_items=[
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC17"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="手电参数"),
        ],
        refreshed_projection_items=[
            SimpleNamespace(start_time=0.0, end_time=1.0, text_final="这是EDC"),
            SimpleNamespace(start_time=1.0, end_time=2.0, text_final="17参数缺字"),
        ],
    )


def test_resolve_subtitle_split_profile_uses_relaxed_landscape_defaults() -> None:
    from roughcut.pipeline.steps import _resolve_subtitle_split_profile

    profile = _resolve_subtitle_split_profile(width=1920, height=1080)

    assert profile == {
        "orientation": "landscape",
        "max_chars": 34,
        "max_duration": 5.8,
    }


def test_resolve_subtitle_split_profile_uses_spoken_portrait_defaults() -> None:
    from roughcut.pipeline.steps import _resolve_subtitle_split_profile

    profile = _resolve_subtitle_split_profile(width=1080, height=1920)

    assert profile == {
        "orientation": "portrait",
        "max_chars": 18,
        "max_duration": 4.2,
    }


def test_relaxed_subtitle_split_profile_expands_landscape_once() -> None:
    from roughcut.pipeline.steps import _relaxed_subtitle_split_profile

    profile = _relaxed_subtitle_split_profile(
        {"orientation": "landscape", "max_chars": 34, "max_duration": 5.8}
    )

    assert profile is not None
    assert profile["orientation"] == "landscape"
    assert profile["max_chars"] == 40
    assert profile["max_duration"] == pytest.approx(6.8)
    assert profile["base_max_chars"] == 34
    assert profile["base_max_duration"] == pytest.approx(5.8)
    assert profile["auto_relaxed"] is True
    assert _relaxed_subtitle_split_profile(profile) is None


def test_subtitle_segmentation_profile_retry_uses_defect_rank() -> None:
    from roughcut.pipeline.steps import (
        _subtitle_segmentation_candidate_is_better,
        _subtitle_segmentation_needs_profile_retry,
    )

    clean = SimpleNamespace(
        protected_term_split_count=0,
        generic_word_split_count=0,
        fragment_start_count=0,
        fragment_end_count=0,
        suspicious_boundary_count=0,
        low_confidence_window_count=1,
    )
    bad = SimpleNamespace(
        protected_term_split_count=0,
        generic_word_split_count=1,
        fragment_start_count=0,
        fragment_end_count=0,
        suspicious_boundary_count=0,
        low_confidence_window_count=0,
    )
    noisy = SimpleNamespace(
        protected_term_split_count=0,
        generic_word_split_count=0,
        fragment_start_count=0,
        fragment_end_count=0,
        suspicious_boundary_count=0,
        low_confidence_window_count=6,
    )

    assert not _subtitle_segmentation_needs_profile_retry(clean)
    assert _subtitle_segmentation_needs_profile_retry(bad)
    assert _subtitle_segmentation_needs_profile_retry(noisy)
    assert _subtitle_segmentation_candidate_is_better(bad, clean)
    assert not _subtitle_segmentation_candidate_is_better(clean, bad)


def test_manual_editor_change_plan_detects_subtitle_only_edits() -> None:
    previous = [{"start": 0.0, "end": 2.0}, {"start": 4.0, "end": 5.0}]
    next_segments = [{"start": 0.01, "end": 2.0}, {"start": 4.0, "end": 5.0}]

    assert not _manual_keep_segments_changed(previous, next_segments)
    plan = _manual_editor_change_plan(
        previous_keep_segments=previous,
        next_keep_segments=next_segments,
        subtitle_overrides=[{"index": 0, "text_final": "new"}],
    )

    assert plan["change_scope"] == "subtitle_only"
    assert plan["render_strategy"] == "reuse_timeline_effect_plan"
    assert plan["timeline_changed"] is False
    assert plan["subtitle_changed"] is True


def test_manual_editor_change_contract_reuses_scope_for_rerun_and_detail() -> None:
    contract = _manual_editor_change_contract(
        {
            "change_scope": "subtitle_only",
            "render_strategy": "reuse_timeline_effect_plan",
            "timeline_changed": False,
            "subtitle_changed": True,
            "video_transform_changed": False,
            "rotation_changed": False,
        }
    )

    assert contract == {
        "change_scope": "subtitle_only",
        "render_strategy": "reuse_timeline_effect_plan",
        "timeline_changed": False,
        "subtitle_changed": True,
        "video_transform_changed": False,
        "packaging_changed": False,
        "rotation_changed": False,
    }
    assert _manual_editor_rerun_issue_code(contract) == "manual_subtitle_edit"
    assert "复用原剪辑/特效计划" in _manual_editor_apply_detail(contract["change_scope"])


def test_manual_editor_rerun_plan_skips_no_material_change_rerun() -> None:
    contract = _manual_editor_change_contract(
        {
            "change_scope": "no_material_change",
            "render_strategy": "metadata_refresh_render",
            "timeline_changed": False,
            "subtitle_changed": False,
            "video_transform_changed": False,
            "packaging_changed": False,
            "rotation_changed": False,
        }
    )

    assert _manual_editor_rerun_plan(contract) == {
        "rerun_start_step": "",
        "rerun_steps": [],
    }
    assert "无需触发剪辑重跑" in _manual_editor_apply_detail(contract["change_scope"])


def test_manual_editor_change_contract_consistency_accepts_no_material_and_rejects_mismatch() -> None:
    assert manual_editor_change_contract_is_consistent(
        {
            "change_scope": "no_material_change",
            "render_strategy": "metadata_refresh_render",
            "timeline_changed": False,
            "subtitle_changed": False,
            "video_transform_changed": False,
            "packaging_changed": False,
            "rotation_changed": False,
        }
    ) is True
    assert manual_editor_change_contract_is_consistent(
        {
            "change_scope": "subtitle_only",
            "render_strategy": "metadata_refresh_render",
            "timeline_changed": False,
            "subtitle_changed": True,
            "video_transform_changed": False,
            "packaging_changed": False,
            "rotation_changed": False,
        }
    ) is False


def test_manual_editor_change_plan_detects_packaging_only_edits() -> None:
    plan = _manual_editor_change_plan(
        previous_keep_segments=[{"start": 0.0, "end": 2.0}],
        next_keep_segments=[{"start": 0.0, "end": 2.0}],
        subtitle_overrides=[],
        previous_hyperframes_options={"progress_bar": False},
        next_hyperframes_options={"progress_bar": True},
    )
    contract = _manual_editor_change_contract(plan)

    assert plan["change_scope"] == "packaging"
    assert plan["render_strategy"] == "packaging_only_render"
    assert plan["packaging_changed"] is True
    assert manual_editor_change_contract_is_consistent(contract) is True
    assert _manual_editor_rerun_plan(contract) == {
        "rerun_start_step": "render",
        "rerun_steps": ["render"],
    }
    assert _manual_editor_rerun_issue_code(contract) == "manual_packaging_edit"
    assert "外挂包装设置已保存" in _manual_editor_apply_detail(contract["change_scope"])


def test_manual_editor_change_plan_detects_timeline_edits() -> None:
    plan = _manual_editor_change_plan(
        previous_keep_segments=[{"start": 0.0, "end": 2.0}],
        next_keep_segments=[{"start": 0.0, "end": 2.4}],
        subtitle_overrides=[],
    )

    assert plan["change_scope"] == "timeline"
    assert plan["render_strategy"] == "full_timeline_render"
    assert plan["timeline_changed"] is True


def test_manual_editor_projection_items_are_authoritative_for_render() -> None:
    items = _manual_editor_subtitle_items_from_editorial(
        {
            "subtitle_projection": {
                "items": [
                    {"index": 2, "start_time": 1.2345, "end_time": 2.0, "text_final": "manual"},
                    {"index": 3, "start_time": 2.0, "end_time": 2.0, "text_final": "invalid"},
                ]
            }
        }
    )

    assert items == [
        {
            "index": 2,
            "start_time": 1.234,
            "end_time": 2.0,
            "text_raw": "",
            "text_norm": "",
            "text_final": "manual",
        }
    ]


def test_manual_editor_projection_items_accept_start_end_keys() -> None:
    items = _manual_editor_subtitle_items_from_editorial(
        {
            "subtitle_projection": {
                "items": [
                    {"index": 2, "start": 99.26, "end": 101.18, "text_final": "但是这个确实是"},
                ]
            }
        }
    )

    assert items == [
        {
            "index": 2,
            "start_time": 99.26,
            "end_time": 101.18,
            "text_raw": "",
            "text_norm": "",
            "text_final": "但是这个确实是",
        }
    ]


def test_manual_editor_projection_items_do_not_backfill_canonical_from_display_surface() -> None:
    items = _manual_editor_subtitle_items_from_editorial(
        {
            "subtitle_projection": {
                "items": [
                    {
                        "index": 7,
                        "start_time": 4.0,
                        "end_time": 5.0,
                        "text_raw": "你看到的是EC手电",
                        "text_norm": "你看到的是EDC手电",
                        "text_final": "看到 EDC 手电",
                    }
                ]
            }
        }
    )

    assert items == [
        {
            "index": 7,
            "start_time": 4.0,
            "end_time": 5.0,
            "text_raw": "你看到的是EC手电",
            "text_norm": "你看到的是EDC手电",
            "text_final": "看到 EDC 手电",
        }
    ]


def test_subtitle_projection_entry_payload_accepts_both_timing_key_styles() -> None:
    assert _subtitle_projection_entry_payload(
        {"index": 1, "start": 99.26, "end": 101.18, "text_final": "artifact"}
    ) == {
        "index": 1,
        "start_time": 99.26,
        "end_time": 101.18,
        "text_raw": None,
        "text_norm": None,
        "text_final": "artifact",
        "display_suppressed_reason": None,
        "projection_source": None,
    }

    assert _subtitle_projection_entry_payload(
        {"index": 2, "start_time": 101.18, "end_time": 104.993, "text_final": "api style"}
    ) == {
        "index": 2,
        "start_time": 101.18,
        "end_time": 104.993,
        "text_raw": None,
        "text_norm": None,
        "text_final": "api style",
        "display_suppressed_reason": None,
        "projection_source": None,
    }


def test_subtitle_projection_entry_payload_preserves_surface_metadata() -> None:
    assert _subtitle_projection_entry_payload(
        {
            "index": 3,
            "start_time": 104.993,
            "end_time": 107.0,
            "text_raw": "那个 E C 手电",
            "text_norm": "EDC手电",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
            "projection_source": "canonical_transcript",
            "words_json": [{"word": "EDC", "start": 105.0, "end": 105.2}],
        }
    ) == {
        "index": 3,
        "start_time": 104.993,
        "end_time": 107.0,
        "text_raw": "那个 E C 手电",
        "text_norm": "EDC手电",
        "text_final": "",
        "display_suppressed_reason": "standalone_filler",
        "projection_source": "canonical_transcript",
        "words": [{"word": "EDC", "start": 105.0, "end": 105.2}],
    }


def test_manual_editor_subtitle_projection_entry_payload_preserves_surface_metadata() -> None:
    payload = jobs_module._manual_editor_subtitle_projection_entry_payload(
        {
            "index": 3,
            "start_time": 104.993,
            "end_time": 107.0,
            "text_raw": "那个 E C 手电",
            "text_norm": "EDC手电",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
            "projection_source": "canonical_transcript",
            "source_index": 9,
            "source_indexes": [9, 10],
            "source_overlap_start_time": 106.0,
            "source_overlap_end_time": 108.0,
            "words_json": [{"word": "EDC", "start": 105.0, "end": 105.2}],
        }
    )

    assert payload == {
        "index": 3,
        "start_time": 104.993,
        "end_time": 107.0,
        "text_raw": "那个 E C 手电",
        "text_norm": "EDC手电",
        "text_final": "",
        "display_suppressed_reason": "standalone_filler",
        "projection_source": "canonical_transcript",
        "source_index": 9,
        "source_indexes": [9, 10],
        "source_overlap_start_time": 106.0,
        "source_overlap_end_time": 108.0,
        "words": [{"word": "EDC", "start": 105.0, "end": 105.2}],
    }


def test_subtitle_item_payload_preserves_display_suppressed_reason() -> None:
    item = SimpleNamespace(
        item_index=4,
        start_time=1.0,
        end_time=2.0,
        text_raw="那个 E C 手电",
        text_norm="EDC手电",
        text_final="",
        display_suppressed_reason="standalone_filler",
    )

    assert _subtitle_item_payload(item) == {
        "index": 4,
        "start_time": 1.0,
        "end_time": 2.0,
        "text_raw": "那个 E C 手电",
        "text_norm": "EDC手电",
        "text_final": "",
        "display_suppressed_reason": "standalone_filler",
        "projection_source": "subtitle_item",
    }


def test_manual_editor_subtitle_item_payload_preserves_surface_metadata() -> None:
    payload = jobs_module._manual_editor_subtitle_item_payload(
        SimpleNamespace(
            item_index=5,
            start_time=2.0,
            end_time=3.0,
            text_raw="那个 E C 手电",
            text_norm="EDC手电",
            text_final="",
            display_suppressed_reason="standalone_filler",
        )
    )

    assert payload == {
        "index": 5,
        "start_time": 2.0,
        "end_time": 3.0,
        "text_raw": "那个 E C 手电",
        "text_norm": "EDC手电",
        "text_final": "",
        "display_suppressed_reason": "standalone_filler",
        "projection_source": "subtitle_item",
    }


def test_manual_editor_ignores_stored_projection_with_runaway_timing() -> None:
    items = _manual_editor_subtitle_items_from_editorial(
        {
            "subtitle_projection": {
                "items": [
                    {"index": 0, "start_time": 41.709, "end_time": 52.656, "text_final": "因为这款啊非常"},
                    {"index": 1, "start_time": 52.676, "end_time": 57.64, "text_final": "正常字幕长度"},
                ]
            }
        }
    )

    assert items == []


def test_manual_editor_rejects_short_subtitle_with_runaway_duration() -> None:
    assert _projection_has_suspicious_subtitle_timing(
        [
            {"index": 0, "start_time": 41.709, "end_time": 52.656, "text_final": "因为这款啊非常"},
            {"index": 1, "start_time": 52.676, "end_time": 57.64, "text_final": "正常字幕长度"},
        ],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )

    assert not _projection_has_suspicious_subtitle_timing(
        [
            {"index": 0, "start_time": 41.709, "end_time": 44.0, "text_final": "因为这款啊"},
            {"index": 1, "start_time": 44.02, "end_time": 47.1, "text_final": "非常火爆"},
        ],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )


def test_manual_editor_rejects_projection_rows_with_output_fallback_alignment() -> None:
    assert _projection_has_suspicious_subtitle_timing(
        [
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 3.0,
                "text_final": "正常长度",
                "words": [
                    {
                        "word": "正常",
                        "start": 1.0,
                        "end": 2.0,
                        "alignment": {"source": "postprocess_text_fallback"},
                    }
                ],
            }
        ],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )


def test_manual_editor_sanitize_projection_item_drops_source_timeline_words_from_output_rows() -> None:
    sanitized = _manual_editor_sanitize_projection_item(
        {
            "index": 236,
            "start_time": 441.017,
            "end_time": 441.617,
            "text_final": "带37了",
            "transcript_text": "我直接带EDC37了",
            "words": [
                {"word": "我", "start": 486.68, "end": 486.98},
                {"word": "直", "start": 487.06, "end": 487.10},
                {"word": "接", "start": 487.10, "end": 487.14},
                {"word": "带", "start": 487.14, "end": 487.42},
                {"word": "3", "start": 487.42, "end": 487.52},
                {"word": "7", "start": 487.52, "end": 487.70},
                {"word": "了", "start": 487.70, "end": 487.84},
            ],
        }
    )

    assert sanitized["text_final"] == "带37了"
    assert "words" not in sanitized
    assert "transcript_text" not in sanitized

    preserved = _manual_editor_sanitize_projection_item(
        {
            "index": 236,
            "start_time": 440.457,
            "end_time": 441.617,
            "text_final": "我直接带EDC37了",
            "transcript_text": "我直接带EDC37了",
            "words": [
                {"word": "我", "start": 440.457, "end": 440.757},
                {"word": "直接", "start": 440.837, "end": 441.297},
                {"word": "带", "start": 441.297, "end": 441.397},
                {"word": "EDC37", "start": 441.397, "end": 441.537},
                {"word": "了", "start": 441.537, "end": 441.617},
            ],
        }
    )

    assert "words" in preserved
    assert preserved["transcript_text"] == "我直接带EDC37了"


def test_manual_subtitle_rerun_preserves_reusable_render_artifacts() -> None:
    artifacts = _artifact_types_for_quality_rerun(
        {"render"},
        issue_codes=["manual_subtitle_edit"],
    )

    assert "render_outputs" not in artifacts
    assert "variant_timeline_bundle" not in artifacts
    assert "platform_packaging_md" not in artifacts


def test_manual_editor_can_open_after_edit_plan_before_full_pipeline_done() -> None:
    steps = [
        SimpleNamespace(step_name="probe", status="done"),
        SimpleNamespace(step_name="extract_audio", status="done"),
        SimpleNamespace(step_name="transcribe", status="done"),
        SimpleNamespace(step_name="subtitle_postprocess", status="done"),
        SimpleNamespace(step_name="subtitle_term_resolution", status="done"),
        SimpleNamespace(step_name="subtitle_consistency_review", status="done"),
        SimpleNamespace(step_name="glossary_review", status="done"),
        SimpleNamespace(step_name="transcript_review", status="done"),
        SimpleNamespace(step_name="subtitle_translation", status="skipped"),
        SimpleNamespace(step_name="content_profile", status="done"),
        SimpleNamespace(step_name="summary_review", status="done"),
        SimpleNamespace(step_name="dialogue_polish", status="done"),
        SimpleNamespace(step_name="avatar_commentary", status="done"),
        SimpleNamespace(step_name="edit_plan", status="done"),
        SimpleNamespace(step_name="render", status="pending"),
    ]

    assert _manual_editor_prerequisite_detail(steps) is None
    assert _manual_editor_apply_conflict_detail(steps) is None


def test_manual_editor_can_open_when_review_gate_pending_after_edit_plan() -> None:
    steps = [
        SimpleNamespace(step_name="probe", status="done"),
        SimpleNamespace(step_name="extract_audio", status="done"),
        SimpleNamespace(step_name="transcribe", status="done"),
        SimpleNamespace(step_name="subtitle_postprocess", status="done"),
        SimpleNamespace(step_name="subtitle_term_resolution", status="done"),
        SimpleNamespace(step_name="subtitle_consistency_review", status="done"),
        SimpleNamespace(step_name="glossary_review", status="done"),
        SimpleNamespace(step_name="transcript_review", status="done"),
        SimpleNamespace(step_name="subtitle_translation", status="skipped"),
        SimpleNamespace(step_name="content_profile", status="done"),
        SimpleNamespace(step_name="summary_review", status="pending"),
        SimpleNamespace(step_name="dialogue_polish", status="skipped"),
        SimpleNamespace(step_name="avatar_commentary", status="done"),
        SimpleNamespace(step_name="edit_plan", status="done"),
        SimpleNamespace(step_name="render", status="pending"),
    ]

    assert _manual_editor_prerequisite_detail(steps) is None
    assert _manual_editor_apply_conflict_detail(steps) is None


def test_manual_editor_prerequisites_ignore_optional_creative_steps_before_edit_plan() -> None:
    steps = [
        SimpleNamespace(step_name="probe", status="done"),
        SimpleNamespace(step_name="extract_audio", status="done"),
        SimpleNamespace(step_name="transcribe", status="done"),
        SimpleNamespace(step_name="subtitle_postprocess", status="done"),
        SimpleNamespace(step_name="subtitle_term_resolution", status="done"),
        SimpleNamespace(step_name="subtitle_consistency_review", status="done"),
        SimpleNamespace(step_name="glossary_review", status="done"),
        SimpleNamespace(step_name="transcript_review", status="done"),
        SimpleNamespace(step_name="subtitle_translation", status="done"),
        SimpleNamespace(step_name="content_profile", status="done"),
        SimpleNamespace(step_name="summary_review", status="done"),
        SimpleNamespace(step_name="dialogue_polish", status="skipped"),
        SimpleNamespace(step_name="avatar_commentary", status="pending"),
        SimpleNamespace(step_name="edit_plan", status="done"),
        SimpleNamespace(step_name="render", status="pending"),
    ]

    assert _manual_editor_prerequisite_detail(steps) is None
    assert _manual_editor_apply_conflict_detail(steps) is None


def test_manual_editor_save_blocks_when_render_is_running() -> None:
    steps = [
        SimpleNamespace(step_name="probe", status="done"),
        SimpleNamespace(step_name="extract_audio", status="done"),
        SimpleNamespace(step_name="transcribe", status="done"),
        SimpleNamespace(step_name="subtitle_postprocess", status="done"),
        SimpleNamespace(step_name="subtitle_term_resolution", status="done"),
        SimpleNamespace(step_name="subtitle_consistency_review", status="done"),
        SimpleNamespace(step_name="glossary_review", status="done"),
        SimpleNamespace(step_name="transcript_review", status="done"),
        SimpleNamespace(step_name="subtitle_translation", status="skipped"),
        SimpleNamespace(step_name="content_profile", status="done"),
        SimpleNamespace(step_name="summary_review", status="done"),
        SimpleNamespace(step_name="dialogue_polish", status="done"),
        SimpleNamespace(step_name="avatar_commentary", status="done"),
        SimpleNamespace(step_name="edit_plan", status="done"),
        SimpleNamespace(step_name="render", status="running"),
    ]

    assert _manual_editor_prerequisite_detail(steps) is None
    assert "正在运行" in str(_manual_editor_apply_conflict_detail(steps))


def test_manual_editor_base_revision_detects_stale_timeline() -> None:
    current_timeline_id = uuid4()
    render_plan_id = uuid4()

    _validate_manual_editor_base_revision(
        ManualEditorApplyIn(
            base_timeline_id=str(current_timeline_id),
            base_timeline_version=3,
            base_render_plan_version=2,
        ),
        editorial_timeline=SimpleNamespace(id=current_timeline_id, version=3),
        render_plan_timeline=SimpleNamespace(id=render_plan_id, version=2),
    )

    with pytest.raises(HTTPException) as exc_info:
        _validate_manual_editor_base_revision(
            ManualEditorApplyIn(
                base_timeline_id=str(uuid4()),
                base_timeline_version=3,
                base_render_plan_version=2,
            ),
            editorial_timeline=SimpleNamespace(id=current_timeline_id, version=3),
            render_plan_timeline=SimpleNamespace(id=render_plan_id, version=2),
        )
    assert exc_info.value.status_code == 409


def test_manual_editor_preview_asset_helpers_are_bounded() -> None:
    assert [round(item, 3) for item in _thumbnail_timestamps(10.0)] == [1.0, 3.0, 5.0, 7.0, 9.0]
    assert len(_thumbnail_timestamps(120.0)) == 5
    assert _thumbnail_timestamps(0.0) == []
    assert _peak_from_pcm((32767).to_bytes(2, "little", signed=True), sample_width=2, channels=1) > 0.99
    assert _recommended_preview_gain(audio_lufs=-32.0) > 6.0
    assert _recommended_preview_gain(audio_lufs=-10.0) < 1.0
    assert _recommended_preview_gain(audio_lufs=None, audio_rms=0.0) == 1.0


def test_manual_editor_normalizes_silence_payloads() -> None:
    silence = _manual_editor_silence_payload({"start": 1.23456, "end": 2.5, "source": "preview_vad"})

    assert silence is not None
    assert silence.start == 1.235
    assert silence.end == 2.5
    assert silence.duration_sec == 1.265
    assert silence.source == "preview_vad"
    assert _manual_editor_silence_payload({"start": 1.0, "end": 1.03}) is None


def test_manual_editor_peak_fallback_detects_long_silence_intervals() -> None:
    peaks = [0.08] * 10 + [0.001] * 20 + [0.09] * 10

    intervals = _silence_intervals_from_peaks(peaks, duration_sec=4.0)

    assert intervals == [{"start": 1.0, "end": 3.0, "duration_sec": 2.0}]


def test_manual_editor_preview_asset_status_is_normalized() -> None:
    status = _fallback_asset_status(
        {
            "asset_version": 2,
            "status": "warming",
            "stage": "waveform_peaks",
            "progress": 1.8,
            "detail": "working",
        }
    )

    assert status["asset_version"] == 2
    assert status["status"] == "warming"
    assert status["stage"] == "waveform_peaks"
    assert status["progress"] == 1.0
    assert status["detail"] == "working"
    assert status["error"] is None


def test_manual_editor_preview_asset_response_exposes_partial_video_proxy() -> None:
    job_id = uuid4()

    response = _manual_editor_preview_assets_response(
        job_id,
        {
            "ready": False,
            "video_ready": True,
            "video_fallback_ready": True,
            "audio_ready": False,
            "video_path": r"C:\roughcut\jobs\job\manual-editor\proxy.mp4",
            "video_fallback_path": r"C:\roughcut\jobs\job\manual-editor\proxy.webm",
            "audio_path": r"C:\roughcut\jobs\job\manual-editor\proxy.wav",
            "status": "warming",
            "stage": "proxy_audio",
            "progress": 0.28,
        },
        ready=False,
        warming=True,
    )

    assert response.ready is False
    assert response.video_ready is True
    assert response.audio_ready is False
    assert response.warming is True
    assert response.video_url == f"/api/v1/jobs/{job_id}/manual-editor/assets/proxy.mp4"
    assert [source.url for source in response.video_sources] == [
        f"/api/v1/jobs/{job_id}/manual-editor/assets/proxy.mp4",
        f"/api/v1/jobs/{job_id}/manual-editor/assets/proxy.webm",
    ]
    assert response.video_sources[0].type == 'video/mp4; codecs="avc1.42E01F, mp4a.40.2"'
    assert response.video_sources[1].type == 'video/webm; codecs="vp8, opus"'
    assert response.audio_url is None


def test_manual_editor_preview_asset_status_hides_proxy_while_ffmpeg_is_writing(tmp_path) -> None:
    job_id = uuid4()
    source_path = tmp_path / "source.mp4"
    asset_dir = tmp_path / "manual-editor"
    source_path.write_bytes(b"source")
    asset_dir.mkdir()
    source_fingerprint = manual_editor_assets_module._source_fingerprint(source_path)
    (asset_dir / "proxy.mp4").write_bytes(b"partial mp4")
    (asset_dir / "proxy.webm").write_bytes(b"partial webm")
    (asset_dir / "status.json").write_text(
        (
            "{"
            f'"asset_version":{manual_editor_assets_module.MANUAL_EDITOR_PREVIEW_ASSET_VERSION},'
            '"status":"warming",'
            '"stage":"proxy_video",'
            '"progress":0.08,'
            f'"source_fingerprint":"{source_fingerprint}"'
            "}"
        ),
        encoding="utf-8",
    )

    payload = load_manual_editor_preview_assets(
        job_id=job_id,
        source_path=source_path,
        duration_sec=10,
        asset_dir=asset_dir,
    )

    assert payload["ready"] is False
    assert payload["video_ready"] is False
    assert payload["video_fallback_ready"] is False


def test_manual_editor_preview_asset_status_exposes_mp4_after_proxy_video_completes(tmp_path) -> None:
    job_id = uuid4()
    source_path = tmp_path / "source.mp4"
    asset_dir = tmp_path / "manual-editor"
    source_path.write_bytes(b"source")
    asset_dir.mkdir()
    source_fingerprint = manual_editor_assets_module._source_fingerprint(source_path)
    (asset_dir / "proxy.mp4").write_bytes(b"complete mp4")
    (asset_dir / "proxy.webm").write_bytes(b"still writing webm")
    (asset_dir / "status.json").write_text(
        (
            "{"
            f'"asset_version":{manual_editor_assets_module.MANUAL_EDITOR_PREVIEW_ASSET_VERSION},'
            '"status":"warming",'
            '"stage":"proxy_webm",'
            '"progress":0.18,'
            f'"source_fingerprint":"{source_fingerprint}"'
            "}"
        ),
        encoding="utf-8",
    )

    payload = load_manual_editor_preview_assets(
        job_id=job_id,
        source_path=source_path,
        duration_sec=10,
        asset_dir=asset_dir,
    )

    assert payload["ready"] is False
    assert payload["video_ready"] is True
    assert payload["video_fallback_ready"] is False


def test_manual_editor_asset_dir_can_live_under_output_project(tmp_path) -> None:
    job_id = uuid4()
    output_project_dir = tmp_path / "20260513_video"

    asset_dir = manual_editor_asset_dir(job_id, output_project_dir=output_project_dir)

    assert asset_dir == output_project_dir / "manual-editor"


def test_output_dir_falls_back_from_windows_path_inside_container() -> None:
    output_dir = output_module._resolve_configured_output_dir(
        "C:\\sample-output",
        "/app/data/output",
        platform_name="posix",
    )

    assert output_dir == "/app/data/output"


def test_manual_editor_asset_path_prefers_output_dir_and_falls_back(tmp_path) -> None:
    job_id = uuid4()
    output_asset_dir = tmp_path / "output" / "manual-editor"
    legacy_asset_dir = tmp_path / "jobs" / str(job_id) / "manual-editor"
    output_asset_dir.mkdir(parents=True)
    legacy_asset_dir.mkdir(parents=True)
    (legacy_asset_dir / "proxy.mp4").write_bytes(b"legacy")
    (output_asset_dir / "thumb_000.jpg").write_bytes(b"thumb")

    assert _manual_editor_asset_path(job_id, "thumb_000.jpg", asset_dirs=[output_asset_dir, legacy_asset_dir]) == output_asset_dir / "thumb_000.jpg"
    assert _manual_editor_asset_path(job_id, "proxy.mp4", asset_dirs=[output_asset_dir, legacy_asset_dir]) == legacy_asset_dir / "proxy.mp4"
    assert _manual_editor_asset_path(job_id, "../proxy.mp4", asset_dirs=[output_asset_dir, legacy_asset_dir]) == legacy_asset_dir / "proxy.mp4"


def test_manual_editor_preview_files_are_served_inline(tmp_path) -> None:
    path = tmp_path / "proxy.mp4"
    path.write_bytes(b"not-a-real-mp4")

    response = _inline_file_response(path)

    assert response.media_type == "video/mp4"
    assert response.headers["content-disposition"].startswith("inline;")

    webm_path = tmp_path / "proxy.webm"
    webm_path.write_bytes(b"not-a-real-webm")

    webm_response = _inline_file_response(webm_path)

    assert webm_response.media_type == "video/webm"
    assert webm_response.headers["content-disposition"].startswith("inline;")


def test_manual_editor_proxy_video_uses_browser_compatible_h264(monkeypatch, tmp_path) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        if "-c:v" in cmd:
            captured["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"proxy")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(manual_editor_assets_module.subprocess, "run", fake_run)

    _generate_proxy_video(tmp_path / "source.mp4", tmp_path / "proxy.mp4")

    cmd = captured["cmd"]
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-profile:v") + 1] == "baseline"
    assert cmd[cmd.index("-level:v") + 1] == "3.1"
    assert "-noautorotate" in cmd
    assert "format=yuv420p" in cmd[cmd.index("-vf") + 1]
    assert "sidedata=mode=delete:type=DISPLAYMATRIX" in cmd[cmd.index("-vf") + 1]


def test_manual_editor_proxy_video_applies_visual_orientation_decision(monkeypatch, tmp_path) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        if "-c:v" in cmd:
            captured["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"proxy")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(manual_editor_assets_module.subprocess, "run", fake_run)

    _generate_proxy_video(
        tmp_path / "source.mp4",
        tmp_path / "proxy.mp4",
        orientation_decision={"rotation_cw": 90, "source": "vision", "confidence": 0.91},
    )

    vf = captured["cmd"][captured["cmd"].index("-vf") + 1]
    assert "-noautorotate" in captured["cmd"]
    assert vf.startswith("transpose=1,sidedata=mode=delete:type=DISPLAYMATRIX,")
    assert "format=yuv420p" in vf


def test_manual_editor_proxy_webm_uses_open_browser_codec_fallback(monkeypatch, tmp_path) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, **_kwargs):
        if "-c:v" in cmd:
            captured["cmd"] = cmd
            Path(cmd[-1]).write_bytes(b"proxy")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(manual_editor_assets_module.subprocess, "run", fake_run)

    _generate_proxy_webm(tmp_path / "source.mp4", tmp_path / "proxy.webm")

    cmd = captured["cmd"]
    assert cmd[cmd.index("-c:v") + 1] == "libvpx"
    assert cmd[cmd.index("-c:a") + 1] == "libopus"
    assert "-noautorotate" in cmd
    assert "format=yuv420p" in cmd[cmd.index("-vf") + 1]
    assert "sidedata=mode=delete:type=DISPLAYMATRIX" in cmd[cmd.index("-vf") + 1]


def test_manual_editor_preview_thumbnails_ignore_bad_rotation_metadata(monkeypatch, tmp_path) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        captured.append(cmd)
        Path(cmd[-1]).write_bytes(b"thumb")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(manual_editor_assets_module.subprocess, "run", fake_run)

    thumbnails = manual_editor_assets_module._generate_preview_thumbnails(
        tmp_path / "source.mp4",
        asset_dir=tmp_path,
        duration_sec=2.0,
    )

    assert thumbnails
    cmd = captured[0]
    assert "-noautorotate" in cmd
    assert "sidedata=mode=delete:type=DISPLAYMATRIX" in cmd[cmd.index("-vf") + 1]


def test_manual_editor_preview_thumbnails_apply_visual_orientation_decision(monkeypatch, tmp_path) -> None:
    captured: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        captured.append(cmd)
        Path(cmd[-1]).write_bytes(b"thumb")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(manual_editor_assets_module.subprocess, "run", fake_run)

    thumbnails = manual_editor_assets_module._generate_preview_thumbnails(
        tmp_path / "source.mp4",
        asset_dir=tmp_path,
        duration_sec=2.0,
        orientation_decision={"rotation_cw": 270, "source": "vision", "confidence": 0.88},
    )

    assert thumbnails
    cmd = captured[0]
    vf = cmd[cmd.index("-vf") + 1]
    assert "-noautorotate" in cmd
    assert vf.startswith("transpose=2,sidedata=mode=delete:type=DISPLAYMATRIX,")
    assert vf.endswith("scale=320:-2")


def test_file_response_cache_validates_and_invalidates_local_files(tmp_path) -> None:
    job_id = uuid4()
    source_path = tmp_path / "source.mp4"
    download_path = tmp_path / "download.mp4"
    source_path.write_bytes(b"source")
    download_path.write_bytes(b"download")

    _source_file_cache_set(job_id, source_path)
    _download_file_cache_set(job_id, "packaged", download_path)

    assert _source_file_cache_get(job_id) == source_path
    assert _download_file_cache_get(job_id, "packaged") == download_path

    source_path.write_bytes(b"source changed")

    assert _source_file_cache_get(job_id) is None

    _invalidate_job_file_response_cache(job_id)

    assert _download_file_cache_get(job_id, "packaged") is None
@pytest.mark.asyncio
async def test_manual_editor_projection_loader_rebuilds_stale_cached_projection_without_sync_rebuild_duplicate_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()

    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.info: dict[str, object] = {}

        def add(self, artifact: object) -> None:
            self.added.append(artifact)

    async def _fake_load_latest_optional_artifact(*args: object, **kwargs: object) -> SimpleNamespace | None:
        artifact_types = tuple(kwargs.get("artifact_types") or ())
        if artifact_types == (ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,):
            return SimpleNamespace(
                step_id=uuid4(),
                data_json={
                    "segmentation_engine_version": "legacy",
                    "canonical_alignment_engine_version": "legacy",
                    "transcript_layer": "canonical_transcript",
                    "entries": [
                        {
                            "index": 0,
                            "start": 0.0,
                            "end": 1.0,
                            "text_raw": "旧分句",
                            "text_norm": "旧分句",
                            "text_final": "旧分句",
                        }
                    ],
                },
            )
        return None

    async def _fake_load_latest_current_canonical_transcript_data(*args: object, **kwargs: object) -> dict[str, object]:
        return {"segments": [{"index": 0, "start": 0.0, "end": 1.4, "text": "重建分句"}]}

    async def _fake_rebuild_projection_entries(*args: object, **kwargs: object) -> tuple[list[dict[str, object]], dict[str, object]]:
        return (
            [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 1.4,
                    "text_raw": "重建分句",
                    "text_norm": "重建分句",
                    "text_final": "重建分句",
                    "projection_source": "canonical_transcript",
                }
            ],
            {
                "segmentation_engine_version": SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
                "split_profile_version": SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
                "canonical_alignment_engine_version": CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION,
                "transcript_layer": "canonical_transcript",
                "entries": [
                    {
                        "index": 0,
                        "start": 0.0,
                        "end": 1.4,
                        "text_raw": "重建分句",
                        "text_norm": "重建分句",
                        "text_final": "重建分句",
                    }
                ],
            },
        )

    monkeypatch.setattr(jobs_module, "_load_latest_optional_artifact", _fake_load_latest_optional_artifact)
    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_latest_current_canonical_transcript_data",
        _fake_load_latest_current_canonical_transcript_data,
    )
    monkeypatch.setattr(
        jobs_module,
        "_manual_editor_rebuild_projection_entries_from_canonical_layer",
        _fake_rebuild_projection_entries,
    )

    fake_session = _FakeSession()
    rows, projection_data = await jobs_module._load_manual_editor_latest_subtitle_projection_entries(
        fake_session,
        job_id=job_id,
        fallback_items=None,
    )

    assert [row["text_final"] for row in rows] == ["重建分句"]
    assert [row.get("projection_source") for row in rows] == ["canonical_transcript"]
    assert projection_data["projection_refresh_required"] is True
    assert projection_data["rebuilt_from_canonical_fallback"] is True
    assert not fake_session.added
    assert not fake_session.info
