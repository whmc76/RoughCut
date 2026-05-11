from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from roughcut.api.jobs import ManualEditorApplyIn
from roughcut.api.jobs import (
    _apply_manual_subtitle_overrides,
    _annotate_manual_projected_subtitle_sources,
    _build_editorial_segments_from_keep_segments,
    _build_otio_style_manual_tracks,
    _clean_manual_editor_subtitle_projection,
    _download_file_cache_get,
    _download_file_cache_set,
    _invalidate_job_file_response_cache,
    _manual_editor_has_collapsed_repeat_runs,
    _manual_editor_subtitle_payload,
    _manual_editor_apply_conflict_detail,
    _manual_editor_change_plan,
    _manual_editor_prerequisite_detail,
    _source_file_cache_get,
    _source_file_cache_set,
    _validate_manual_editor_base_revision,
    _manual_keep_segments_changed,
    _normalize_manual_keep_segments,
)
from roughcut.edit.otio_export import export_to_otio
from roughcut.media.manual_editor_assets import _fallback_asset_status, _peak_from_pcm, _recommended_preview_gain, _thumbnail_timestamps
from roughcut.pipeline.orchestrator import _artifact_types_for_quality_rerun
from roughcut.pipeline.steps import (
    _manual_editor_subtitle_items_from_editorial,
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


def test_manual_editor_subtitle_payload_uses_final_output_cleanup() -> None:
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

    assert payload.text_final == "好 今天给大家介绍 狐蝠工业"


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

    assert payload.text_final == "给它塞进去啊"
    assert noise_payload.text_final == "好"


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
