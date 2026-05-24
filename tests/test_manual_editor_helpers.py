from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from roughcut.api.jobs import ManualEditorApplyIn
from roughcut.api.jobs import (
    _apply_manual_subtitle_overrides,
    _annotate_manual_projected_subtitle_sources,
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
    _manual_editor_apply_source_text_corrections,
    _manual_editor_apply_transcript_hotword_corrections,
    _manual_editor_asset_path,
    _manual_editor_canonical_segment_source_rows,
    _manual_editor_change_plan,
    _manual_editor_prerequisite_detail,
    _manual_editor_preview_assets_response,
    _manual_editor_normalize_word_payloads_for_text,
    _manual_editor_projected_subtitles_have_duplicate_source_overlap,
    _manual_editor_projection_should_use_source_fallback,
    _manual_editor_profile_has_vertical_glossary_evidence,
    _manual_editor_reveal_source_asr_words,
    _manual_editor_split_long_subtitle_rows,
    _manual_projection_has_source_text_mismatch,
    _manual_editor_smart_delete_segments,
    _manual_keep_segments_from_editorial_payload,
    _source_file_cache_get,
    _source_file_cache_set,
    _validate_manual_editor_base_revision,
    _manual_keep_segments_changed,
    _normalize_manual_keep_segments,
)
from roughcut.edit.otio_export import export_to_otio
from roughcut.media import manual_editor_assets as manual_editor_assets_module
from roughcut.media import output as output_module
from roughcut.media.manual_editor_assets import _fallback_asset_status, _generate_proxy_video, _generate_proxy_webm, _peak_from_pcm, _recommended_preview_gain, _silence_intervals_from_peaks, _thumbnail_timestamps, load_manual_editor_preview_assets, manual_editor_asset_dir
from roughcut.media.subtitle_projection_validation import (
    validate_projected_subtitles_against_source,
    validate_projected_subtitles_against_transcript,
)
from roughcut.pipeline.orchestrator import _artifact_types_for_quality_rerun
from roughcut.pipeline.steps import (
    _manual_editor_subtitle_items_from_editorial,
    _normalize_subtitle_event,
    _projection_has_suspicious_subtitle_timing,
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


def test_manual_editor_smart_delete_segments_expose_auto_waste_cuts() -> None:
    segments = _manual_editor_smart_delete_segments(
        {
            "accepted_cuts": [
                {
                    "start": 1.2345,
                    "end": 3.5,
                    "reason": "restart_retake",
                    "llm_review": {
                        "verdict": "cut",
                        "confidence": 0.91,
                        "reason": "前一句明确说重来，后一句是重录版本。",
                        "evidence": ["重来提示", "后一句重复表达"],
                    },
                    "evidence": {"previous_text": "说错了重来", "next_text": "正式开始"},
                },
                {
                    "start": 4.0,
                    "end": 5.0,
                    "reason": "silence",
                    "llm_review": {"verdict": "keep", "confidence": 0.88},
                },
                {
                    "start": 6.0,
                    "end": 6.4,
                    "reason": "silence",
                    "llm_review": {"verdict": "cut", "confidence": 0.8},
                },
            ],
            "manual_editor_rule_candidates": [
                {
                    "start": 7.0,
                    "end": 7.2,
                    "reason": "filler_word",
                    "score": 0.86,
                    "candidate_stage": "manual_editor_full_transcript",
                    "auto_applied": False,
                }
            ],
        }
    )

    assert len(segments) == 3
    assert segments[0].start == 1.234
    assert segments[0].end == 3.5
    assert segments[0].source == "llm_cut_review"
    assert segments[0].confidence == 0.91
    assert segments[0].detail == "前一句明确说重来，后一句是重录版本。"
    assert segments[1].start == 6.0
    assert segments[1].end == 6.4
    assert segments[1].source == "llm_cut_review"
    assert segments[2].start == 7.0
    assert segments[2].end == 7.2
    assert segments[2].source == "manual_editor_rule_candidate"
    assert segments[2].confidence == 0.86
    assert segments[2].detail == "规则候选：口头填充音"


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


def test_manual_editor_uses_canonical_projection_even_when_cleaning_drops_repeats() -> None:
    repeated = "刚才我发现那个盒子放底下有点黑看不清它的这个全貌"
    raw = [
        {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": repeated},
        {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": repeated},
        {"index": 2, "start_time": 2.0, "end_time": 3.0, "text_final": repeated},
    ]
    cleaned = _clean_manual_editor_subtitle_projection(raw)

    assert not _manual_editor_should_use_clean_fallback_projection(
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
            '"asset_version":10,'
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
            '"asset_version":10,'
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
        captured["cmd"] = cmd
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
        captured["cmd"] = cmd
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
