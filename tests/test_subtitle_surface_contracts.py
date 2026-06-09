from types import SimpleNamespace

from roughcut.creative.avatar import _normalize_subtitle_items as _normalize_avatar_subtitle_items
from roughcut.api.jobs import _manual_editor_projection_has_suspicious_subtitle_timing
from roughcut.api.jobs import _manual_editor_projection_rows_as_source_rows
from roughcut.api.jobs import _manual_editor_display_source_text
from roughcut.api.jobs import _manual_editor_final_subtitle_text
from roughcut.api.jobs import _manual_editor_timing_text
from roughcut.edit.decisions import _normalize_subtitle_items
from roughcut.edit.render_plan import _normalize_overlay_text
from roughcut.edit.subtitle_surfaces import (
    subtitle_canonical_rule_text,
    subtitle_display_rule_text,
    subtitle_raw_rule_text,
)
from roughcut.media.subtitle_fingerprint import subtitle_payload_fingerprint
from roughcut.media.subtitle_projection_validation import subtitle_projection_display_text
from roughcut.media.subtitle_spans import subtitle_display_text as subtitle_span_display_text
from roughcut.media.subtitles import _subtitle_item_display_text
from roughcut.media.subtitle_text import clean_subtitle_payloads
from roughcut.edit.timeline_contract import (
    _normalize_subtitle_ranges,
    _normalize_suppressed_subtitle_ranges,
)
from roughcut.pipeline.steps import (
    _build_projection_entries_from_subtitle_items,
    _projection_item_text,
    _subtitle_text,
)
from roughcut.review.subtitle_quality import _subtitle_text as subtitle_quality_text


def test_subtitle_surface_helpers_keep_raw_canonical_and_display_separate() -> None:
    item = {
        "transcript_text_raw": "它算是定位相当高端的一款EC手电了",
        "text_raw": "它算是定位相当高端的一款EC手电了",
        "transcript_text": "它算是定位相当高端的一款EDC手电了",
        "text_norm": "它算是定位相当高端的一款EDC手电了",
        "text_final": "定位高端的EDC手电",
        "projection_text": "高端 EDC 手电",
    }

    assert subtitle_raw_rule_text(item) == "它算是定位相当高端的一款EC手电了"
    assert subtitle_canonical_rule_text(item) == "它算是定位相当高端的一款EDC手电了"
    assert subtitle_display_rule_text(item) == "高端 EDC 手电"


def test_subtitle_surface_helpers_use_owned_fallbacks_before_cross_layer_fallback() -> None:
    item = {
        "text_raw": "原始口播",
        "text_norm": "规范文本",
        "text_final": "展示字幕",
    }

    assert subtitle_raw_rule_text(item) == "原始口播"
    assert subtitle_canonical_rule_text(item) == "规范文本"
    assert subtitle_display_rule_text(item) == "展示字幕"


def test_timeline_contract_display_ranges_follow_display_surface() -> None:
    subtitle_items = [
        {
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "啊",
            "text_norm": "啊",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
        },
        {
            "start_time": 1.0,
            "end_time": 2.0,
            "text_raw": "它算是定位相当高端的一款EC手电了",
            "text_norm": "它算是定位相当高端的一款EDC手电了",
            "text_final": "它算是定位相当高端的一款EDC手电了",
        },
    ]

    assert _normalize_subtitle_ranges(subtitle_items) == [(1.0, 2.0)]
    assert _normalize_suppressed_subtitle_ranges(subtitle_items) == [
        {"start": 0.0, "end": 1.0, "reason": "standalone_filler"}
    ]


def test_render_consumers_use_display_surface_not_raw_surface() -> None:
    item = {
        "text_raw": "你看到的是EC手电",
        "text_norm": "你看到的是EDC手电",
        "text_final": "看到 EDC 手电",
    }

    assert _subtitle_text(item) == "看到 EDC 手电"
    assert _normalize_overlay_text(item) == "看到EDC手电"


def test_pipeline_object_surface_helpers_respect_display_suppression() -> None:
    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=1.0,
        text_raw="啊",
        text_norm="啊",
        text_final="",
        display_suppressed_reason="standalone_filler",
    )

    assert _projection_item_text(item) == ""
    assert _build_projection_entries_from_subtitle_items([item], use_final_text=True)[0].text_raw == ""


def test_manual_editor_projection_rows_preserve_explicit_surfaces() -> None:
    rows = _manual_editor_projection_rows_as_source_rows(
        [
            {
                "index": 3,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "它算是定位相当高端的一款EC手电了",
                "text_norm": "它算是定位相当高端的一款EDC手电了",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        projection_data={"transcript_layer": "canonical_transcript"},
    )

    assert rows[0]["text_raw"] == "它算是定位相当高端的一款EC手电了"
    assert rows[0]["text_norm"] == "它算是定位相当高端的一款EDC手电了"
    assert rows[0]["text_final"] == ""


def test_decision_subtitle_normalization_uses_surface_contract() -> None:
    normalized = _normalize_subtitle_items(
        [
            {
                "start_time": 0.0,
                "end_time": 1.0,
                "text_raw": "你看到的是EC手电",
                "text_norm": "你看到的是EDC手电",
                "projection_text": "看到 EDC 手电",
                "text_final": "看到 EDC 手电",
            }
        ]
    )

    assert normalized[0]["text_raw"] == "你看到的是EC手电"
    assert normalized[0]["text_norm"] == "你看到的是EDC手电"
    assert normalized[0]["text_final"] == "看到 EDC 手电"


def test_projection_validation_display_text_respects_display_suppression() -> None:
    item = {
        "text_raw": "啊",
        "text_norm": "啊",
        "text_final": "",
        "display_suppressed_reason": "standalone_filler",
    }

    assert subtitle_projection_display_text(item) == ""


def test_shared_display_helpers_respect_surface_contract() -> None:
    item = {
        "text_raw": "独立语气词",
        "text_norm": "独立语气词",
        "text_final": "",
        "display_suppressed_reason": "standalone_filler",
    }

    assert subtitle_span_display_text(item) == ""
    assert _subtitle_item_display_text(item) == ""
    assert subtitle_quality_text(item) == ""


def test_manual_editor_text_helpers_respect_surface_contract() -> None:
    item = {
        "text_raw": "啊",
        "text_norm": "啊",
        "text_final": "",
        "display_suppressed_reason": "standalone_filler",
    }

    assert _manual_editor_final_subtitle_text(item) == ""
    assert _manual_editor_display_source_text(item) == ""
    assert _manual_editor_timing_text(item) == ""


def test_subtitle_fingerprint_ignores_display_suppressed_rows() -> None:
    fingerprint = subtitle_payload_fingerprint(
        [
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "text_raw": "啊",
                "text_norm": "啊",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            },
            {
                "index": 1,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "EC手电",
                "text_norm": "EDC手电",
                "text_final": "EDC手电",
            },
        ]
    )

    expected = subtitle_payload_fingerprint(
        [
            {
                "index": 1,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "EDC手电",
            }
        ]
    )

    assert fingerprint == expected


def test_avatar_normalization_drops_rows_hidden_by_display_surface() -> None:
    normalized = _normalize_avatar_subtitle_items(
        [
            {
                "start_time": 0.0,
                "end_time": 0.8,
                "text_raw": "啊",
                "text_norm": "啊",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            },
            {
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "你看到的是EC手电",
                "text_norm": "你看到的是EDC手电",
                "text_final": "看到 EDC 手电",
            },
        ]
    )

    assert len(normalized) == 1
    assert normalized[0]["text_final"] == "看到 EDC 手电"


def test_clean_subtitle_payloads_uses_display_surface_contract() -> None:
    cleaned = clean_subtitle_payloads(
        [
            {
                "start_time": 0.0,
                "end_time": 1.0,
                "text_raw": "你看到的是EC手电",
                "text_norm": "你看到的是EDC手电",
                "projection_text": "看到 EDC 手电",
            }
        ]
    )

    assert cleaned[0]["text_final"] == "看到 EDC 手电"


def test_manual_editor_suspicious_timing_uses_display_surface_contract() -> None:
    assert not _manual_editor_projection_has_suspicious_subtitle_timing(
        [
            {
                "start_time": 0.0,
                "end_time": 12.0,
                "text_raw": "啊",
                "text_norm": "啊",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )
