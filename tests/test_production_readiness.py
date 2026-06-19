import json

from roughcut.media.output import get_cover_manifest_path, load_cover_selection_summary
from roughcut.production_readiness import (
    creator_refine_output_fallback_reasons,
    intelligent_copy_cover_brief_fallback_reasons,
    intelligent_copy_material_context_fallback_reasons,
    insert_plan_output_fallback_reasons,
    platform_packaging_output_fallback_reasons,
    projection_output_fallback_reasons,
    render_output_blocking_reasons,
)


def test_projection_output_fallback_reasons_distinguishes_refresh_from_real_fallback() -> None:
    diagnostics = {
        "projection_refresh_required": True,
        "rebuilt_from_canonical_fallback": True,
        "source_projection_fallback_applied": False,
        "projection_validation_fallback_used": False,
    }

    assert projection_output_fallback_reasons(diagnostics) == [
        "subtitle_projection_rebuilt_from_canonical_fallback",
    ]
    assert projection_output_fallback_reasons(diagnostics, include_refresh_required=True) == [
        "subtitle_projection_rebuilt_from_canonical_fallback",
        "subtitle_projection_refresh_required",
    ]
    assert projection_output_fallback_reasons({"fallback_used": True}) == [
        "subtitle_projection_validation_fallback_used",
    ]


def test_platform_packaging_output_fallback_reasons_block_deterministic_or_renderless_outputs() -> None:
    packaging = {
        "generation_repair_trace": [{"status": "deterministic_fallback"}],
        "subtitle_projection_repair": {"projection_validation_fallback_used": True},
    }

    assert platform_packaging_output_fallback_reasons(packaging, renderless_mode=False) == [
        "platform_packaging_deterministic_fallback",
        "subtitle_projection_validation_fallback_used",
    ]
    assert platform_packaging_output_fallback_reasons({}, renderless_mode=True) == [
        "platform_packaging_renderless_only",
    ]


def test_render_output_blocking_reasons_ignore_optional_runtime_degradation() -> None:
    reasons = render_output_blocking_reasons(
        avatar_result={"status": "degraded", "reason": "missing_avatar_render"},
        subtitle_projection_repair={"projection_validation_fallback_used": True},
    )

    assert reasons == [
        "subtitle_projection_validation_fallback_used",
    ]
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
    ) == []


def test_creator_refine_and_insert_plan_fallbacks_are_blocking() -> None:
    assert creator_refine_output_fallback_reasons({"source": "rule_fallback"}) == [
        "creator_refine_rule_fallback",
    ]
    assert insert_plan_output_fallback_reasons({"selection_source": "deterministic_fallback"}) == [
        "insert_slot_deterministic_fallback",
    ]
    assert intelligent_copy_cover_brief_fallback_reasons({"strategy_source": "fallback"}) == [
        "intelligent_copy_cover_brief_fallback",
    ]
    assert intelligent_copy_material_context_fallback_reasons(
        packaging={"generation_repair_trace": [{"status": "deterministic_fallback"}]},
        cover_brief={"strategy_source": "fallback"},
    ) == [
        "platform_packaging_deterministic_fallback",
        "intelligent_copy_cover_brief_fallback",
    ]


def test_cover_selection_summary_marks_primary_fallback_output(tmp_path) -> None:
    output_path = tmp_path / "cover.png"
    output_path.write_bytes(b"cover")
    manifest_path = get_cover_manifest_path(output_path)
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "index": 1,
                    "path": str(output_path),
                    "seek_sec": 0.0,
                    "strategy_key": "fallback",
                    "strategy_label": "基础兜底",
                    "reason": "cover_generation_fallback",
                    "title_style": "preset_default",
                    "title": {"line1": "标题"},
                    "score": 0.0,
                    "ranking_source": "fallback",
                    "rank": 1,
                    "is_primary": True,
                    "review_recommended": False,
                    "score_gap_to_next": None,
                    "review_reason": "",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = load_cover_selection_summary(output_path)

    assert summary is not None
    assert summary["fallback_generated"] is True
    assert summary["fallback_reason"] == "cover_generation_fallback"
    assert summary["ranking_source"] == "fallback"
