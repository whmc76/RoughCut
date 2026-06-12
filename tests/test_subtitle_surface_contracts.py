from types import SimpleNamespace

from roughcut.creative.avatar import _normalize_subtitle_items as _normalize_avatar_subtitle_items
from roughcut.api.jobs import _manual_editor_projection_has_suspicious_subtitle_timing
from roughcut.api.jobs import _manual_editor_editable_final_subtitle_text
from roughcut.api.jobs import _manual_editor_projection_rows_as_source_rows
from roughcut.api.jobs import _manual_editor_display_source_text
from roughcut.api.jobs import _manual_editor_final_subtitle_text
from roughcut.api.jobs import _manual_editor_timing_text
from roughcut.edit.decisions import _normalize_subtitle_items
from roughcut.edit.render_plan import _normalize_overlay_text
from roughcut.edit.subtitle_surfaces import (
    subtitle_canonical_explicit_text,
    subtitle_canonical_rule_text,
    subtitle_display_rule_text,
    subtitle_raw_explicit_text,
    subtitle_raw_rule_text,
    subtitle_semantic_item_text,
    subtitle_surface_item_dict,
)
from roughcut.review.content_profile import _content_profile_semantic_text
from roughcut.review.subtitle_translation import _subtitle_translation_source_text
from roughcut.review.content_profile import _transcript_evidence_items as content_profile_transcript_evidence_items
from roughcut.review.content_understanding_evidence import _transcript_excerpt_items
from roughcut.media.subtitle_fingerprint import subtitle_payload_fingerprint
from roughcut.media.subtitle_projection_validation import subtitle_projection_display_text
from roughcut.media.subtitle_spans import subtitle_display_text as subtitle_span_display_text
from roughcut.media.subtitles import _subtitle_item_display_text
from roughcut.media.subtitle_text import clean_subtitle_payloads
from roughcut.review.subtitle_consistency import build_subtitle_consistency_report
from roughcut.review.subtitle_quality import build_subtitle_quality_report_from_items
from roughcut.edit.timeline_contract import (
    _normalize_subtitle_ranges,
    _normalize_suppressed_subtitle_ranges,
)
from roughcut.pipeline.steps import (
    _build_fallback_canonical_words,
    _build_projection_entries_from_subtitle_items,
    _build_edit_plan_transcript_segments,
    _normalize_transcript_segment_payloads,
    _projection_has_suspicious_subtitle_timing,
    _projection_item_text,
    _subtitle_text,
)
from roughcut.review.subtitle_quality import _subtitle_text as subtitle_quality_text
from roughcut.speech.subtitle_pipeline import _build_projection_entries_from_transcript_words


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


def test_subtitle_surface_item_dict_preserves_explicit_surfaces_without_cross_fill() -> None:
    item = {
        "text_raw": "你看到的是EC手电",
        "text_norm": "你看到的是EDC手电",
        "text_final": "看到 EDC 手电",
    }

    assert subtitle_surface_item_dict(item, generic_fallback_text="generic") == {
        "text_raw": "你看到的是EC手电",
        "text_norm": "你看到的是EDC手电",
        "text_final": "看到 EDC 手电",
    }


def test_subtitle_surface_item_dict_only_uses_generic_text_when_no_explicit_surface_exists() -> None:
    assert subtitle_surface_item_dict({"text": "generic"}, generic_fallback_text="generic") == {
        "text_raw": "generic",
        "text_norm": "generic",
        "text_final": "generic",
    }


def test_subtitle_semantic_item_text_preserves_explicit_canonical_surface_over_generic_text() -> None:
    item = {
        "text": "generic text should not override canonical surface",
        "text_raw": "你看到的是EC手电",
        "text_norm": "你看到的是EDC手电",
    }

    assert subtitle_semantic_item_text(item, generic_fallback_text=str(item["text"])) == "你看到的是EDC手电"
    assert _content_profile_semantic_text(item) == "你看到的是EDC手电"
    assert _subtitle_translation_source_text(item) == "你看到的是EDC手电"


def test_review_transcript_evidence_items_preserve_surface_distinctions() -> None:
    transcript_evidence = {
        "segments": [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.0,
                "text_raw": "你看到的是EC手电",
                "text_norm": "你看到的是EDC手电",
                "text_final": "看到 EDC 手电",
            }
        ]
    }

    profile_items = content_profile_transcript_evidence_items(transcript_evidence)
    understanding_items = _transcript_excerpt_items(transcript_evidence)

    assert profile_items[0]["text_raw"] == "你看到的是EC手电"
    assert profile_items[0]["text_norm"] == "你看到的是EDC手电"
    assert profile_items[0]["text_final"] == "看到 EDC 手电"
    assert understanding_items[0]["text_raw"] == "你看到的是EC手电"
    assert understanding_items[0]["text_norm"] == "你看到的是EDC手电"
    assert understanding_items[0]["text_final"] == "看到 EDC 手电"


def test_normalize_transcript_segment_payloads_preserve_raw_and_canonical_surfaces() -> None:
    items = _normalize_transcript_segment_payloads(
        [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.0,
                "text": "generic text should not erase explicit surfaces",
                "text_raw": "你看到的是EC手电",
                "text_canonical": "你看到的是EDC手电",
            }
        ]
    )

    assert items == [
        {
            "index": 0,
            "start": 0.0,
            "end": 1.0,
            "text": "你看到的是EDC手电",
            "text_raw": "你看到的是EC手电",
            "text_canonical": "你看到的是EDC手电",
            "text_norm": "你看到的是EDC手电",
            "text_final": "",
            "speaker": None,
            "confidence": None,
            "logprob": None,
            "alignment": None,
            "words": [],
        }
    ]


def test_build_fallback_canonical_words_prefers_explicit_canonical_surface_over_generic_text() -> None:
    words = _build_fallback_canonical_words(
        {
            "start": 0.0,
            "end": 1.0,
            "text": "generic text should not override canonical transcript",
            "text_raw": "你看到的是EC手电",
            "text_canonical": "你看到的是EDC手电",
        }
    )

    assert "".join(str(item["word"]) for item in words) == "你看到的是EDC手电"


def test_build_edit_plan_transcript_segments_emits_surface_aware_fallback_shape() -> None:
    rows = _build_edit_plan_transcript_segments(
        [
            SimpleNamespace(
                segment_index=0,
                start_time=0.0,
                end_time=1.0,
                text="你看到的是EC手电",
                speaker=None,
                words_json=[],
            )
        ],
        None,
    )

    assert rows == [
        {
            "index": 0,
            "start": 0.0,
            "end": 1.0,
            "text": "你看到的是EC手电",
            "text_raw": "你看到的是EC手电",
            "text_canonical": "你看到的是EC手电",
            "text_norm": "你看到的是EC手电",
            "text_final": "你看到的是EC手电",
            "speaker": None,
            "words": [],
        }
    ]


def test_explicit_surface_helpers_do_not_cross_fill_between_layers() -> None:
    item = {
        "text_final": "展示字幕",
    }

    assert subtitle_raw_explicit_text(item) == ""
    assert subtitle_canonical_explicit_text(item) == ""
    assert subtitle_display_rule_text(item) == "展示字幕"


def test_display_rule_text_is_suppressed_when_no_text_final_exists() -> None:
    item = {
        "text_raw": "噪音",
        "text_norm": "噪音",
        "display_suppressed_reason": "asr_noise_marker",
    }

    assert subtitle_display_rule_text(item) == ""


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


def test_projection_validation_display_text_does_not_fallback_legacy_text_for_suppressed_rows() -> None:
    item = {
        "text_raw": "这个",
        "text_norm": "这个",
        "text": "这个",
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


def test_subtitle_quality_report_from_items_preserves_display_suppression_contract() -> None:
    report = build_subtitle_quality_report_from_items(
        subtitle_items=[
            {
                "index": 0,
                "text_raw": "独立语气词",
                "text_norm": "独立语气词",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
                "start_time": 0.0,
                "end_time": 1.0,
            },
            SimpleNamespace(
                index=1,
                text_raw="看一下细节",
                text_norm="看一下细节",
                text_final="看一下细节",
                start_time=1.0,
                end_time=2.0,
                display_suppressed_reason=None,
            ),
        ]
    )

    assert report["metrics"]["subtitle_count"] == 2
    assert report["metrics"]["filler_count"] == 0


def test_subtitle_consistency_report_uses_display_surface_contract() -> None:
    report = build_subtitle_consistency_report(
        subtitle_items=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "text_raw": "今天继续开枪",
                "text_norm": "今天继续开箱",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        source_name="demo.mp4",
    )

    assert report["metrics"]["subtitle_count"] == 1
    assert report["conflicts"]["subtitle_vs_filename"] == []


def test_manual_editor_text_helpers_respect_surface_contract() -> None:
    item = {
        "text_raw": "啊",
        "text_norm": "啊",
        "text_final": "",
        "display_suppressed_reason": "asr_noise_marker",
    }

    assert _manual_editor_final_subtitle_text(item) == ""
    assert _manual_editor_editable_final_subtitle_text(item) == ""
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


def test_pipeline_suspicious_timing_uses_display_surface_contract() -> None:
    assert not _projection_has_suspicious_subtitle_timing(
        [
            {
                "start_time": 0.0,
                "end_time": 12.0,
                "text": "generic fallback should not revive suppressed display text",
                "text_raw": "啊",
                "text_norm": "啊",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        split_profile={"max_chars": 30, "max_duration": 5.0},
    )


def test_transcript_word_projection_entries_do_not_prewrite_display_surface() -> None:
    entries = _build_projection_entries_from_transcript_words(
        [
            SimpleNamespace(
                index=0,
                start=0.0,
                end=1.0,
                text="你看到的是EC手电",
                words=[
                    {"word": "你看到的是", "start": 0.0, "end": 0.4},
                    {"word": "EC手电", "start": 0.4, "end": 1.0},
                ],
            )
        ],
        max_chars=30,
        max_duration=5.0,
    )

    assert len(entries) == 1
    assert entries[0].text_raw == "你看到的是EC手电"
    assert entries[0].text_norm
    assert entries[0].text_final is None


def test_transcript_word_projection_entries_prefer_explicit_canonical_surface_from_dict_segments() -> None:
    entries = _build_projection_entries_from_transcript_words(
        [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.0,
                "text": "generic text should not override canonical transcript",
                "text_canonical": "你看到的是EDC手电",
                "words": [
                    {"word": "你看到的是", "start": 0.0, "end": 0.4},
                    {"word": "EDC手电", "start": 0.4, "end": 1.0},
                ],
            }
        ],
        max_chars=30,
        max_duration=5.0,
    )

    assert len(entries) == 1
    assert entries[0].text_raw == "你看到的是EDC手电"
    assert "你看到的是EDC手电" in entries[0].text_norm
    assert entries[0].text_final is None
