from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from roughcut.api import jobs as jobs_module
from roughcut.api.jobs import ManualEditorApplyIn
from roughcut.api.jobs import (
    _apply_manual_subtitle_overrides,
    _annotate_manual_projected_subtitle_sources,
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
    _manual_editor_projection_entries_use_canonical,
    _manual_editor_apply_conflict_detail,
    _manual_editor_sanitize_projection_item,
    _manual_editor_transcript_projection_blocking_is_significant,
    _manual_editor_apply_source_text_corrections,
    _manual_editor_apply_transcript_hotword_corrections,
    _manual_editor_asset_path,
    _manual_editor_canonical_segment_source_rows,
    _manual_editor_change_plan,
    _manual_editor_cut_analysis_payload,
    _manual_editor_prerequisite_detail,
    _manual_editor_preview_assets_response,
    _manual_editor_base_keep_segment_dicts,
    _manual_editor_build_refine_decision_plan_from_render_plan,
    _load_manual_editor_cut_analysis_payload,
    _manual_editor_restore_frontend_managed_auto_cuts,
    _manual_editor_smart_cut_rules_payload,
    _manual_editor_normalize_word_payloads_for_text,
    _manual_editor_projected_subtitles_have_duplicate_source_overlap,
    _manual_editor_projection_baseline_rows,
    _manual_editor_projection_should_use_source_fallback,
    _manual_editor_profile_has_vertical_glossary_evidence,
    _manual_editor_reveal_source_asr_words,
    _manual_editor_rule_segments,
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
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.cut_analysis import build_cut_analysis_payload
from roughcut.edit.refine_decisions import (
    build_refine_decision_plan_from_render_plan,
    build_refine_decision_plan_payload,
    refine_plan_audio_defaults,
    resolve_refine_keep_segments_for_timeline,
)
from roughcut.edit.smart_cut_rules import DEFAULT_SMART_CUT_CATCHPHRASES, DEFAULT_SMART_CUT_FILLERS
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
    _build_edit_review_bundle_payload,
    _build_edited_subtitle_projection,
    _build_variant_timeline_bundle,
    _manual_editor_subtitle_items_from_editorial,
    _normalize_subtitle_event,
    _projection_has_suspicious_subtitle_timing,
    _resolve_keep_segments_from_refine_plan,
    _subtitle_projection_entry_payload,
)


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
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert not _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="fingerprint-b",
        current_timeline_subtitle_fingerprint="fingerprint-c",
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_manual_editor_timeline_matches_either_source_or_projection_fingerprint() -> None:
    payload = {"analysis": {"manual_editor": {"base_subtitle_fingerprint": "source-current"}}}

    assert _manual_editor_timeline_matches_current_subtitles(
        payload,
        current_subtitle_fingerprint="source-current",
        current_timeline_subtitle_fingerprint="projection-current",
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert _manual_editor_timeline_matches_current_subtitles(
        {"analysis": {"manual_editor": {"timeline_subtitle_fingerprint": "projection-current"}}},
        current_subtitle_fingerprint="source-current",
        current_timeline_subtitle_fingerprint="projection-current",
        timeline_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        latest_subtitle_revision_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )


def test_manual_editor_legacy_timeline_is_stale_when_subtitle_revision_is_newer() -> None:
    timeline_created_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    assert not _manual_editor_timeline_matches_current_subtitles(
        {"analysis": {}},
        current_subtitle_fingerprint="fingerprint-a",
        timeline_created_at=timeline_created_at,
        latest_subtitle_revision_created_at=timeline_created_at + timedelta(seconds=1),
    )
    assert _manual_editor_timeline_matches_current_subtitles(
        {"analysis": {}},
        current_subtitle_fingerprint="fingerprint-a",
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
        source_subtitles=[{"start_time": 0.0, "end_time": 1.0, "text_final": "嗯我们开始"}],
        smart_cut_rules={
            "fillerEnabled": True,
            "fillerStandaloneEnabled": True,
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
            "fillerContinuousEnabled": False,
            "catchphraseEnabled": True,
            "fillers": "嗯",
            "catchphrases": "就是",
        },
    )

    candidates = payload["rule_candidates"]
    assert any(item["reason"] == "filler_word" and item["source_text"] == "嗯" and item["filler_mode"] == "standalone" for item in candidates)
    assert any(item["reason"] == "catchphrase_phrase" and item["source_text"] == "就是" for item in candidates)


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
            {"start_time": 0.0, "end_time": 1.0, "text_final": "嗯我们开始"},
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

    reasons = [item["reason"] for item in payload["rule_candidates"]]
    stages = [item.get("candidate_stage") for item in payload["rule_candidates"]]
    assert reasons == ["repeated_speech"]
    assert stages == ["manual_editor_full_transcript"]


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
        "manual_confirm_candidate_count": 0,
    }
    assert bundle["timeline_rules"]["diagnostics"]["refine_decision_summary"] == {
        "mode": "manual_refine",
        "keep_segment_count": 1,
        "candidate_total": 2,
        "candidate_auto_apply": 1,
        "candidate_manual_confirm": 1,
    }


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
    )

    assert payload["topic_fact_confirmation"] == {"status": "confirmed"}
    assert payload["cut_analysis"] == {"schema": "cut_analysis.v1", "candidate_count": 2}
    assert payload["refine_decision_plan"] == {"schema": "refine_decision_plan.v1", "mode": "auto_refine"}
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


def test_backend_smart_cut_candidates_include_low_signal_subtitle_waste() -> None:
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

    assert len(low_signal) == 1
    assert low_signal[0]["start"] == 0.0
    assert low_signal[0]["end"] == 0.9
    assert low_signal[0]["source_text"] == "然后呢"


def test_backend_low_signal_candidates_mark_multimodal_review_when_visual_hint_overlaps() -> None:
    payload = build_cut_analysis_payload(
        editorial_analysis={},
        source_name="demo.mp4",
        job_flow_mode="auto",
        source_subtitles=[
            {"start_time": 0.0, "end_time": 0.9, "text_final": "然后呢"},
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


def test_manual_editor_smart_cut_rules_payload_defaults_when_missing() -> None:
    payload = _manual_editor_smart_cut_rules_payload(None)
    assert payload is not None
    assert payload["fillers"] == DEFAULT_SMART_CUT_FILLERS
    assert payload["catchphrases"] == DEFAULT_SMART_CUT_CATCHPHRASES
    assert payload["pauseThresholdSec"] == 0.8


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
        "auto_apply": 1,
        "manual_confirm": 1,
        "analysis_schema": "cut_analysis.v1",
    }
    assert payload["keep_segments"] == [{"start": 0.0, "end": 8.0}]
    assert payload["smart_cut_rules"]["fillerEnabled"] is True
    assert payload["smart_cut_rules"]["pauseThresholdSec"] == 0.8
    assert payload["smart_cut_rules"]["fillers"] == DEFAULT_SMART_CUT_FILLERS
    assert payload["smart_cut_rules"]["catchphrases"] == DEFAULT_SMART_CUT_CATCHPHRASES


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


def test_manual_editor_revealed_asr_words_tighten_after_filler_trim() -> None:
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
    assert rows[1]["end_time"] == 862.155
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


def test_manual_editor_source_alignment_tightens_anchored_rows_to_display_words() -> None:
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

    assert rows[0]["start_time"] == 26.3
    assert rows[0]["end_time"] == 26.7
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
    assert event["source_index"] == 41
    assert event["source_indexes"] == [41, 42]
    assert event["source_overlap_start_time"] == 101.0


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
            "text_raw": "最近这三次NOC的发售太难了",
            "text_norm": "最近这三次NOC的发售太难了",
            "text_final": "最近这三次NOC的发售太难了",
            "projection_source": "subtitle_item",
        }
    ]


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
    assert any("一款EDC手电了" in text for text in rendered)
    assert any("这个EDC17是什么灯珠啊" in text for text in rendered)
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
    assert rows[0]["transcript_text"] == "啊呃今天主题吧"
    assert "".join(word["word"] for word in rows[0]["words"]) == "啊呃今天主题吧"


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
            "words": [
                {"word": char, "start": 1.0 + index * 0.1, "end": 1.1 + index * 0.1}
                for index, char in enumerate("一个小玩具啊这个也")
            ],
        },
        index=0,
    )

    assert payload.text_final == "一个小玩具这个也"
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


def test_manual_editor_subtitle_projection_keeps_short_repeated_pairs() -> None:
    cleaned = _clean_manual_editor_subtitle_projection(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "这个是真的"},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": "这个是真的"},
        ]
    )

    assert [item["index"] for item in cleaned] == [0, 1]


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
            "text_norm": "manual",
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
            "text_norm": "但是这个确实是",
            "text_final": "但是这个确实是",
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
        {"render", "final_review", "platform_package"},
        issue_codes=["manual_subtitle_edit"],
    )

    assert "render_outputs" not in artifacts
    assert "variant_timeline_bundle" not in artifacts
    assert "platform_packaging_md" in artifacts


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
        SimpleNamespace(step_name="ai_director", status="done"),
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
        SimpleNamespace(step_name="ai_director", status="skipped"),
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
        SimpleNamespace(step_name="ai_director", status="skipped"),
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
        SimpleNamespace(step_name="ai_director", status="done"),
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
        "Y:\\EDC系列\\AI粗剪",
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
    assert "format=yuv420p" in cmd[cmd.index("-vf") + 1]


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
    assert "format=yuv420p" in cmd[cmd.index("-vf") + 1]


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
