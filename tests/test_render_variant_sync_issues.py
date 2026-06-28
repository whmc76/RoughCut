import pytest

from roughcut.pipeline import steps as pipeline_steps
from roughcut.pipeline.steps import (
    _collect_blocking_variant_audio_presence_issues,
    _collect_blocking_variant_sync_issues,
    _repair_subtitles_with_rendered_audio_asr,
    _variant_subtitle_audio_presence_windows,
    _variant_sync_check_with_asr_gap_override,
)
from roughcut.pipeline.quality import _subtitle_timing_structure_diagnostics


def test_collect_blocking_variant_sync_issues_only_checks_required_variants() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "packaged": {"warning_codes": ["subtitle_out_of_bounds"]},
            "plain": {"warning_codes": ["subtitle_duration_gap_large"]},
            "avatar": {"warning_codes": ["subtitle_out_of_bounds"]},
            "ai_effect": {"warning_codes": ["subtitle_trailing_gap_large"]},
        },
        mandatory_variants={"plain", "packaged"},
    )

    assert issues == [
        "packaged: subtitle_out_of_bounds",
        "plain: subtitle_duration_gap_large",
    ]


def test_collect_blocking_variant_sync_issues_ignores_optional_variant_noise_if_not_required() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "plain": {"warning_codes": ["subtitle_timestamp_disorder"]},
            "avatar": {"warning_codes": ["subtitle_timestamp_disorder"]},
        },
        mandatory_variants={"plain"},
    )

    assert issues == ["plain: subtitle_timestamp_disorder"]


def test_collect_blocking_variant_sync_issues_keeps_default_behavior_without_mandatory_variants() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "avatar": {"warning_codes": ["subtitle_timestamp_disorder"]},
            "plain": {"warning_codes": ["subtitle_timestamp_disorder"]},
        }
    )

    assert set(issues) == {
        "avatar: subtitle_timestamp_disorder",
        "plain: subtitle_timestamp_disorder",
    }


def test_collect_blocking_variant_sync_issues_blocks_subtitle_flash_density() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "packaged": {
                "warning_codes": ["subtitle_burst_density_detected", "subtitle_short_flash_detected"],
                "subtitle_timing_structure": {
                    "short_flash_count": 3,
                    "max_events_per_one_sec": 5,
                    "burst_window_count": 1,
                },
            }
        },
        mandatory_variants={"packaged"},
    )

    assert issues == ["packaged: subtitle_burst_density_detected, subtitle_short_flash_detected"]


def test_asr_gap_override_suppresses_only_gap_warnings_after_gate_pass() -> None:
    sync_check = {
        "warning_codes": [
            "subtitle_trailing_gap_large",
            "subtitle_duration_gap_large",
            "subtitle_overlap_detected",
        ],
        "effective_trailing_gap_sec": 12.0,
        "effective_duration_gap_sec": 12.0,
    }

    normalized = _variant_sync_check_with_asr_gap_override(sync_check, {"gate_pass": True})

    assert normalized["warning_codes"] == ["subtitle_overlap_detected"]
    assert normalized["effective_trailing_gap_sec"] == 0.0
    assert normalized["effective_duration_gap_sec"] == 0.0
    assert normalized["asr_gap_override_applied"] is True


def test_asr_gap_override_keeps_gap_warnings_without_gate_pass() -> None:
    sync_check = {
        "warning_codes": ["subtitle_trailing_gap_large"],
        "effective_trailing_gap_sec": 12.0,
    }

    assert _variant_sync_check_with_asr_gap_override(sync_check, {"gate_pass": False}) is sync_check


def test_tail_subtitle_audio_presence_windows_focus_on_late_speech() -> None:
    windows = _variant_subtitle_audio_presence_windows(
        [
            {"start_time": 1.0, "end_time": 4.0, "text_final": "开场"},
            {"start_time": 320.0, "end_time": 326.0, "text_final": "还有人声"},
            {"start_time": 345.0, "end_time": 351.0, "text_final": "这里不能静音"},
            {"start_time": 420.0, "end_time": 426.0, "text_final": "结尾仍然有人声"},
        ],
        tail_ratio=0.72,
        window_sec=6.0,
        limit=4,
    )

    assert windows == [
        {"start_sec": 320.0, "duration_sec": 6.0, "subtitle_end_sec": 326.0},
        {"start_sec": 345.0, "duration_sec": 6.0, "subtitle_end_sec": 351.0},
        {"start_sec": 420.0, "duration_sec": 6.0, "subtitle_end_sec": 426.0},
    ]


def test_collect_blocking_variant_audio_presence_issues_blocks_silent_tail_subtitles() -> None:
    issues = _collect_blocking_variant_audio_presence_issues(
        {
            "packaged": {
                "blocking": True,
                "reason": "tail_subtitle_windows_are_silent",
                "silent_window_count": 3,
                "window_count": 3,
            },
            "ai_effect": {"blocking": False, "silent_window_count": 0, "window_count": 3},
        },
        mandatory_variants={"packaged", "ai_effect"},
    )

    assert issues == ["packaged: tail_subtitle_windows_are_silent (3/3 tail subtitle windows silent)"]


@pytest.mark.asyncio
async def test_audio_presence_audit_treats_zero_returncode_as_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    async def fake_measure_audio_window_volume(*_args, **_kwargs):
        return {"returncode": 0, "mean_volume_db": -20.0, "max_volume_db": -2.0}

    monkeypatch.setattr(pipeline_steps, "_measure_audio_window_volume", fake_measure_audio_window_volume)

    result = await pipeline_steps._audit_variant_subtitle_audio_presence(
        video_path=tmp_path / "candidate.mp4",
        subtitle_items=[
            {"start_time": 300.0, "end_time": 306.0, "text_final": "尾部有人声"},
            {"start_time": 420.0, "end_time": 424.0, "text_final": "结尾有人声"},
        ],
        variant_name="packaged",
        debug_dir=tmp_path,
    )

    assert result["status"] == "pass"
    assert result["blocking"] is False
    assert result["failed_probe_count"] == 0
    assert result["silent_window_count"] == 0


@pytest.mark.asyncio
async def test_rendered_audio_asr_repair_blocks_tail_regression(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    original_subtitles = [
        {"start_time": 0.0, "end_time": 2.0, "text_final": "开箱"},
        {"start_time": 430.0, "end_time": 434.28, "text_final": "结尾仍有人声"},
    ]
    shortened_subtitles = [
        {"start_time": 0.0, "end_time": 2.0, "text_final": "开箱"},
        {"start_time": 371.0, "end_time": 375.78, "text_final": "错误短尾"},
    ]
    audit_payloads = [
        {"gate_pass": False, "duration_sec": 443.264, "audit": {}, "offset_estimate": {"stable": False}},
        {"gate_pass": True, "duration_sec": 443.264, "audit": {}, "offset_estimate": {"stable": True}},
    ]

    async def fake_audit_subtitles_against_rendered_audio(**_kwargs):
        return audit_payloads.pop(0)

    monkeypatch.setattr(pipeline_steps, "_audit_subtitles_against_rendered_audio", fake_audit_subtitles_against_rendered_audio)
    monkeypatch.setattr(
        pipeline_steps,
        "_drop_clustered_unmatched_render_subtitles",
        lambda subtitles, _audit: ([dict(item) for item in subtitles], {}),
    )
    monkeypatch.setattr(
        pipeline_steps,
        "_retime_render_subtitle_items_from_alignment_audit",
        lambda *_args, **_kwargs: ([dict(item) for item in shortened_subtitles], {"retimed": True}),
    )
    monkeypatch.setattr(
        pipeline_steps,
        "_drop_tail_compressed_duplicate_render_subtitles",
        lambda subtitles, _audit: ([dict(item) for item in subtitles], {}),
    )

    repaired, alignment = await _repair_subtitles_with_rendered_audio_asr(
        video_path=tmp_path / "candidate.mp4",
        subtitle_items=original_subtitles,
        language="zh",
        debug_dir=tmp_path,
        label="packaged",
    )

    assert repaired == original_subtitles
    assert alignment["status"] == "blocked"
    assert alignment["reason"] == "rendered_audio_asr_alignment_tail_regression"
    assert alignment["original_last_end_sec"] == 434.28
    assert alignment["candidate_last_end_sec"] == 375.78


def test_subtitle_timing_structure_diagnostics_detects_fast_flash_cluster() -> None:
    diagnostics = _subtitle_timing_structure_diagnostics(
        [
            (1.00, 1.12),
            (1.15, 1.29),
            (1.32, 1.46),
            (1.49, 1.61),
            (4.00, 5.40),
        ],
        video_duration_sec=8.0,
    )

    assert diagnostics["short_flash_count"] == 4
    assert diagnostics["max_events_per_one_sec"] == 4
    assert diagnostics["burst_window_count"] == 1
