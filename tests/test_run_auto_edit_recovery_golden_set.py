from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.build_job_audit_pack import build_markdown as build_audit_markdown
from scripts.export_job_audit_snapshot import (
    _merge_historical_render_context,
    _normalize_render_outputs_summary_for_reporting,
    derive_effective_job_error,
    derive_effective_job_status,
    summarize_render_outputs,
)
from scripts import promote_auto_edit_golden_references as promote_refs
from scripts import run_auto_edit_recovery_golden_set as golden
from roughcut.db.models import Job
from scripts.run_fullchain_batch import JobRunReport, LiveStageValidation, StepRun


def test_load_golden_job_manifest_accepts_rich_job_entries(tmp_path: Path) -> None:
    manifest_path = tmp_path / "golden.json"
    manifest_path.write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "case_id": "manual_editor_edc17",
                        "scenario": "manual editor regression anchor",
                        "reference_job_id": "fb30a42c-1af1-4c78-b065-bc3cd4004b2e",
                        "reference_risk_job_id": "a8b490ec-155d-4cff-85ee-f1316740205a",
                        "source_paths": ["main.mp4", "broll.mp4"],
                        "product_controls": {"edit_mode": "multi_material"},
                        "strategy_classification": {
                            "primary_type": "avatar_commentary_remix",
                            "production_mode": "remix",
                            "media_tags": ["digital_human"],
                            "editing_signals": ["material_insert_required"],
                        },
                        "source_context": {"operator_note": "fixture"},
                        "transcript_segments": [
                            {"start": 0.0, "end": 2.0, "text": "hello fixture"},
                        ],
                        "tags": ["manual_editor", "projection"],
                        "required_checks": ["manual_editor_ready", "subtitle_projection"],
                        "risk_hints": {
                            "reference_high_risk_cut_count": 1,
                            "reference_expected_stage": "render",
                            "fresh_expectations": {
                                "edit_plan": {
                                    "expected_source": "variant_timeline_bundle",
                                    "manual_confirm_hint": 2,
                                }
                            },
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    cases = golden.load_golden_job_manifest(manifest_path)

    assert len(cases) == 1
    assert cases[0].case_id == "manual_editor_edc17"
    assert cases[0].reference_job_id == "fb30a42c-1af1-4c78-b065-bc3cd4004b2e"
    assert cases[0].reference_risk_job_id == "a8b490ec-155d-4cff-85ee-f1316740205a"
    assert cases[0].source_paths == ["main.mp4", "broll.mp4"]
    assert cases[0].enhancement_modes_explicit is False
    assert cases[0].product_controls == {"edit_mode": "multi_material"}
    assert cases[0].strategy_classification == {
        "primary_type": "avatar_commentary_remix",
        "production_mode": "remix",
        "media_tags": ["digital_human"],
        "editing_signals": ["material_insert_required"],
    }
    assert cases[0].source_context == {"operator_note": "fixture"}
    assert cases[0].transcript_segments == [
        {"index": 0, "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "hello fixture"}
    ]
    assert cases[0].tags == ["manual_editor", "projection"]
    assert cases[0].required_checks == ["manual_editor_ready", "subtitle_projection"]
    assert cases[0].risk_hints == {
        "reference_high_risk_cut_count": 1,
        "reference_expected_stage": "render",
        "fresh_expectations": {
            "edit_plan": {
                "expected_source": "variant_timeline_bundle",
                "manual_confirm_hint": 2,
            }
        },
    }


def test_load_golden_job_manifest_tracks_explicit_empty_enhancement_modes(tmp_path: Path) -> None:
    manifest_path = tmp_path / "golden.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "strategy_candidate",
                    "reference_job_id": "fb30a42c-1af1-4c78-b065-bc3cd4004b2e",
                    "enhancement_modes": [],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    cases = golden.load_golden_job_manifest(manifest_path)

    assert cases[0].enhancement_modes == []
    assert cases[0].enhancement_modes_explicit is True


def test_clone_evaluation_job_honors_explicit_empty_enhancement_modes() -> None:
    captured: dict[str, Job] = {}

    class EmptyScalarResult:
        def all(self) -> list[object]:
            return []

        def first(self) -> None:
            return None

    class EmptyExecuteResult:
        def scalars(self) -> EmptyScalarResult:
            return EmptyScalarResult()

    class FakeSession:
        async def execute(self, *_args: object, **_kwargs: object) -> EmptyExecuteResult:
            return EmptyExecuteResult()

        def add(self, item: Job) -> None:
            if isinstance(item, Job):
                captured["job"] = item

        async def flush(self) -> None:
            return None

    source_job = Job(
        id=uuid.uuid4(),
        source_path="jobs/source.mp4",
        source_name="source.mp4",
        file_hash="hash",
        status="done",
        workflow_template="edc_tactical",
        enhancement_modes=["avatar_commentary", "ai_effects"],
    )

    asyncio.run(
        golden._clone_evaluation_job_from_existing(
            FakeSession(),
            source_job=source_job,
            workflow_template="edc_tactical",
            language="zh-CN",
            enhancement_modes=[],
        )
    )

    assert captured["job"].enhancement_modes == []


def test_clone_evaluation_job_inherits_enhancement_modes_when_manifest_does_not_override() -> None:
    captured: dict[str, Job] = {}

    class EmptyScalarResult:
        def all(self) -> list[object]:
            return []

        def first(self) -> None:
            return None

    class EmptyExecuteResult:
        def scalars(self) -> EmptyScalarResult:
            return EmptyScalarResult()

    class FakeSession:
        async def execute(self, *_args: object, **_kwargs: object) -> EmptyExecuteResult:
            return EmptyExecuteResult()

        def add(self, item: Job) -> None:
            if isinstance(item, Job):
                captured["job"] = item

        async def flush(self) -> None:
            return None

    source_job = Job(
        id=uuid.uuid4(),
        source_path="jobs/source.mp4",
        source_name="source.mp4",
        file_hash="hash",
        status="done",
        workflow_template="edc_tactical",
        enhancement_modes=["avatar_commentary", "ai_effects"],
    )

    asyncio.run(
        golden._clone_evaluation_job_from_existing(
            FakeSession(),
            source_job=source_job,
            workflow_template="edc_tactical",
            language="zh-CN",
            enhancement_modes=None,
        )
    )

    assert captured["job"].enhancement_modes == ["avatar_commentary", "ai_effects"]


def test_load_golden_job_manifest_rejects_duplicate_reference_job_ids(tmp_path: Path) -> None:
    manifest_path = tmp_path / "golden.json"
    manifest_path.write_text(
        json.dumps(
            [
                {"case_id": "case_a", "reference_job_id": "same-job"},
                {"case_id": "case_b", "reference_job_id": "same-job"},
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate reference_job_id"):
        golden.load_golden_job_manifest(manifest_path)


def test_load_golden_job_manifest_rejects_unsupported_required_checks(tmp_path: Path) -> None:
    manifest_path = tmp_path / "golden.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "case_a",
                    "reference_job_id": "job-a",
                    "required_checks": ["manual_editor_ready", "not_a_real_gate"],
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported required_checks"):
        golden.load_golden_job_manifest(manifest_path)


def test_prepare_golden_job_uses_merged_sources_and_strategy_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_a = tmp_path / "main.mp4"
    source_b = tmp_path / "broll.mp4"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")
    captured: dict[str, object] = {}

    class FakeSession:
        async def __aenter__(self) -> "FakeSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    def fake_session_factory():
        return lambda: FakeSession()

    async def fake_create_merged_job_for_inventory_paths(file_paths: list[str], **kwargs: object) -> str:
        captured["file_paths"] = file_paths
        captured["kwargs"] = kwargs
        return "merged-job-id"

    monkeypatch.setattr(golden, "get_session_factory", fake_session_factory)
    monkeypatch.setattr(golden, "create_merged_job_for_inventory_paths", fake_create_merged_job_for_inventory_paths)

    async def fake_apply_golden_case_transcript_seed(job_id: str, case: golden.GoldenJobCase) -> None:
        captured["seed_job_id"] = job_id
        captured["seed_case_id"] = case.case_id

    monkeypatch.setattr(golden, "_apply_golden_case_transcript_seed", fake_apply_golden_case_transcript_seed)

    case = golden.GoldenJobCase(
        case_id="strategy-narrative",
        scenario="narrative replay-safe fixture",
        source_paths=[str(source_a), str(source_b)],
        workflow_template="multi_material_story",
        product_controls={"edit_mode": "multi_material"},
        source_context={"operator_note": "fixture"},
        strategy_classification={
            "primary_type": "avatar_commentary_remix",
            "production_mode": "remix",
            "media_tags": ["digital_human"],
            "editing_signals": ["material_insert_required"],
        },
    )

    prepared = asyncio.run(
        golden.prepare_golden_job(
            case,
            default_workflow_template="edc_tactical",
            default_language="zh-CN",
            locate_roots=[],
        )
    )

    assert prepared.job_id == "merged-job-id"
    assert prepared.mode == "fresh_merged_full_chain"
    assert prepared.item["source_paths"] == [str(source_a), str(source_b)]
    assert captured["file_paths"] == [str(source_a), str(source_b)]
    kwargs = captured["kwargs"]
    assert kwargs["workflow_template"] == "multi_material_story"
    assert kwargs["product_controls"] == {"edit_mode": "multi_material"}
    assert kwargs["allow_related_profiles"] is True
    assert kwargs["allow_duplicate_file"] is True
    assert kwargs["content_profile_source_context"] == {
        "operator_note": "fixture",
        "strategy_classification": {
            "primary_type": "avatar_commentary_remix",
            "production_mode": "remix",
            "media_tags": ["digital_human"],
            "editing_signals": ["material_insert_required"],
        },
        "product_controls": {"edit_mode": "multi_material"},
    }
    assert captured["seed_job_id"] == "merged-job-id"
    assert captured["seed_case_id"] == "strategy-narrative"


def test_transcript_seed_does_not_skip_media_artifact_steps() -> None:
    assert "probe" not in golden.TRANSCRIPT_SEED_DONE_STEPS
    assert "extract_audio" not in golden.TRANSCRIPT_SEED_DONE_STEPS
    assert "transcribe" in golden.TRANSCRIPT_SEED_DONE_STEPS
    assert "subtitle_translation" in golden.TRANSCRIPT_SEED_DONE_STEPS


def test_current_golden_manifest_required_checks_are_supported() -> None:
    manifest_path = golden.ROOT / "docs" / "golden-jobs" / "auto-edit-recovery-golden-slice.v1.json"
    cases = golden.load_golden_job_manifest(manifest_path)

    manifest_required_checks = {
        check
        for case in cases
        for check in case.required_checks
    }

    assert manifest_required_checks <= golden.SUPPORTED_REQUIRED_CHECKS


def test_previous_effective_keep_segments_prefers_aligned_refine_plan_over_editorial_full_keep() -> None:
    editorial_payload = {
        "segments": [
            {"type": "keep", "start": 0.0, "end": 20.0},
        ]
    }
    refine_payload = {
        "schema": "refine_decision_plan.v1",
        "mode": "auto_refine",
        "editorial_timeline_id": "timeline-1",
        "editorial_timeline_version": 3,
        "keep_segments": [
            {"start": 0.0, "end": 5.0},
            {"start": 7.0, "end": 20.0},
        ],
    }

    assert golden._previous_effective_keep_segments(
        editorial_timeline_payload=editorial_payload,
        refine_plan_payload=refine_payload,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=3,
    ) == [
        {"start": 0.0, "end": 5.0},
        {"start": 7.0, "end": 20.0},
    ]


def test_previous_effective_keep_segments_falls_back_to_editorial_when_refine_plan_is_misaligned() -> None:
    editorial_payload = {
        "segments": [
            {"type": "keep", "start": 0.0, "end": 5.0},
            {"type": "cut", "start": 5.0, "end": 7.0, "reason": "manual_editor_removed"},
            {"type": "keep", "start": 7.0, "end": 20.0},
        ]
    }
    refine_payload = {
        "schema": "refine_decision_plan.v1",
        "mode": "auto_refine",
        "editorial_timeline_id": "timeline-2",
        "editorial_timeline_version": 99,
        "keep_segments": [{"start": 1.0, "end": 2.0}],
    }

    assert golden._previous_effective_keep_segments(
        editorial_timeline_payload=editorial_payload,
        refine_plan_payload=refine_payload,
        editorial_timeline_id="timeline-1",
        editorial_timeline_version=3,
    ) == [
        {"start": 0.0, "end": 5.0},
        {"start": 7.0, "end": 20.0},
    ]


def test_select_golden_job_cases_filters_by_case_id_and_tag() -> None:
    cases = [
        golden.GoldenJobCase(case_id="case_a", scenario="A", tags=["manual_editor", "projection"]),
        golden.GoldenJobCase(case_id="case_b", scenario="B", tags=["subtitle_segmentation"]),
        golden.GoldenJobCase(case_id="case_c", scenario="C", tags=["manual_editor", "filler_rule"]),
    ]

    selected = golden.select_golden_job_cases(cases, case_ids=["case_c", "case_a"], tags=["manual_editor"])

    assert [case.case_id for case in selected] == ["case_a", "case_c"]


def test_select_golden_job_cases_rejects_unknown_case_id() -> None:
    cases = [
        golden.GoldenJobCase(case_id="case_a", scenario="A"),
    ]

    with pytest.raises(ValueError, match="unknown golden case_id"):
        golden.select_golden_job_cases(cases, case_ids=["missing"])


def test_select_golden_job_cases_rejects_empty_filter_result() -> None:
    cases = [
        golden.GoldenJobCase(case_id="case_a", scenario="A", tags=["manual_editor"]),
    ]

    with pytest.raises(ValueError, match="matched no cases"):
        golden.select_golden_job_cases(cases, tags=["subtitle_segmentation"])


def test_job_requires_audit_for_failed_stage_or_low_score() -> None:
    report = JobRunReport(
        job_id="job-1",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="done",
        output_path="E:/demo_out.mp4",
        cover_path=None,
        output_duration_sec=12.0,
        transcript_segment_count=10,
        subtitle_count=12,
        correction_count=1,
        keep_ratio=0.7,
        cover_variant_count=1,
        platform_doc=None,
        quality_score=82.0,
        quality_grade="B",
        quality_issue_codes=[],
        live_stage_validations=[
            LiveStageValidation(stage="manual_editor_ready", status="pass", summary="ok"),
            LiveStageValidation(stage="subtitle_projection", status="warn", summary="mismatch"),
        ],
        content_profile=None,
        steps=[StepRun(step="render", status="done", elapsed_seconds=1.0)],
        notes=[],
    )

    assert golden.job_requires_audit(report, audit_threshold=75.0) is True

    report.live_stage_validations = [LiveStageValidation(stage="manual_editor_ready", status="pass", summary="ok")]
    assert golden.job_requires_audit(report, audit_threshold=85.0) is True
    assert golden.job_requires_audit(report, audit_threshold=75.0) is False


def test_build_case_result_rows_requires_contract_checks() -> None:
    cases = [
        golden.GoldenJobCase(
            case_id="case-a",
            scenario="contract check anchor",
            source_name="demo.mp4",
            required_checks=["manual_editor_ready", "manual_editor_apply_semantics", "subtitle_projection"],
        ),
    ]
    prepared = [
        golden.PreparedGoldenJob(
            case=cases[0],
            job_id="job-1",
            mode="cloned_full_chain",
            item={"path": "E:/demo.mp4", "source_name": "demo.mp4"},
        ),
    ]
    report = JobRunReport(
        job_id="job-1",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="done",
        output_path="E:/demo_out.mp4",
        cover_path=None,
        output_duration_sec=12.0,
        transcript_segment_count=10,
        subtitle_count=12,
        correction_count=1,
        keep_ratio=0.7,
        cover_variant_count=1,
        platform_doc=None,
        quality_score=82.0,
        quality_grade="B",
        quality_issue_codes=[],
        live_stage_validations=[
            LiveStageValidation(stage="manual_editor_ready", status="pass", summary="ok"),
            LiveStageValidation(stage="subtitle_projection", status="warn", summary="mismatch"),
        ],
        content_profile=None,
        steps=[StepRun(step="render", status="done", elapsed_seconds=1.0)],
        notes=[],
    )
    rows = golden.build_case_result_rows(
        cases,
        prepared,
        [report],
        {"jobs": [{"source_name": "demo.mp4", "editing": {"score": 88}, "subtitle_quality": {"score": 87}}]},
        manual_editor_apply_semantics_by_case={
            "case-a": {
                "ok": True,
                "managed_auto_cut_count": 10,
                "change_scope": "subtitle_only",
                "timeline_changed": False,
                "render_strategy": "reuse_timeline_effect_plan",
                "roundtrip_matches_editorial": True,
                "session_baseline_matches_restored": True,
            }
        },
    )

    assert rows[0]["required_checks_passed"] is False
    assert rows[0]["required_checks_failed"] == ["subtitle_projection"]
    assert rows[0]["manual_editor_ready"] is True
    assert rows[0]["manual_editor_apply_semantics_ok"] is True
    assert rows[0]["manual_editor_render_strategy"] == "reuse_timeline_effect_plan"


def test_build_case_result_rows_includes_reference_risk_snapshot() -> None:
    cases = [
        golden.GoldenJobCase(
            case_id="case-ref-risk",
            scenario="reference risk snapshot anchor",
            source_name="demo.mp4",
            risk_hints={"reference_high_risk_cut_count": 1, "reference_expected_source": "variant_timeline_bundle"},
        ),
    ]
    prepared = [
        golden.PreparedGoldenJob(
            case=cases[0],
            job_id="job-1",
            mode="cloned_full_chain",
            item={"path": "E:/demo.mp4", "source_name": "demo.mp4"},
        ),
    ]
    report = JobRunReport(
        job_id="job-1",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="done",
        output_path="E:/demo_out.mp4",
        cover_path=None,
        output_duration_sec=12.0,
        transcript_segment_count=10,
        subtitle_count=12,
        correction_count=1,
        keep_ratio=0.7,
        cover_variant_count=1,
        platform_doc=None,
        quality_score=82.0,
        quality_grade="B",
        quality_issue_codes=[],
        live_stage_validations=[],
        content_profile=None,
        steps=[StepRun(step="render", status="done", elapsed_seconds=1.0)],
        notes=[],
    )

    rows = golden.build_case_result_rows(
        cases,
        prepared,
        [report],
        {
            "jobs": [
                {
                    "source_name": "demo.mp4",
                    "editing": {"score": 88},
                    "subtitle_quality": {"score": 87},
                    "editing_risk_metrics": {
                        "source": "variant_timeline_bundle",
                        "source_reason": "variant_bundle_available",
                        "high_risk_cut_count": 0,
                        "manual_confirm_count": 7,
                        "multimodal_pending_count": 4,
                        "llm_reviewed": True,
                    },
                }
            ]
        },
        reference_risk_snapshots_by_case={
            "case-ref-risk": {
                "case_id": "case-ref-risk",
                "job_id": "job-ref",
                "source_name": "demo.mp4",
                "artifact_types": ["render_outputs", "variant_timeline_bundle"],
                "variant_bundle_present": True,
                "has_render_outputs": True,
                "has_cut_analysis": False,
                "high_risk_cut_count": 3,
                "manual_confirm_candidate_count": 0,
                "refine_candidate_manual_confirm": 0,
                "multimodal_pending_count": 0,
                "llm_reviewed": False,
                "llm_candidate_count": 3,
                "llm_error": "llm_cut_review_failed",
                "review_recommended": True,
                "review_reasons": ["check boundaries"],
                "first_high_risk_cut_reason": "silence",
            }
        },
    )

    assert rows[0]["reference_risk_snapshot"]["high_risk_cut_count"] == 3
    assert rows[0]["risk_alignment"]["reference_high_risk_cut_count"] == 3
    assert rows[0]["risk_alignment"]["reference_llm_reviewed"] is False
    assert rows[0]["risk_alignment"]["reference_manual_confirm_candidate_count"] == 0


def test_build_case_risk_alignment_prefers_reference_snapshot_manual_confirm_signals() -> None:
    case = golden.GoldenJobCase(
        case_id="case-edit-plan-risk",
        scenario="edit-plan risk anchor",
        risk_hints={
            "reference_expected_stage": "edit_plan",
            "reference_expected_source": "cut_analysis_refine_decision_plan",
            "reference_manual_confirm_candidate_count": 131,
        },
    )
    score = {
        "editing_risk_metrics": {
            "source": "variant_timeline_bundle",
            "source_reason": "variant_bundle_available",
            "high_risk_cut_count": 0,
            "manual_confirm_count": 96,
            "multimodal_pending_count": 1,
            "llm_reviewed": True,
        }
    }

    risk_alignment = golden._build_case_risk_alignment(
        case,
        score,
        reference_risk_snapshot={
            "manual_confirm_candidate_count": 131,
            "refine_candidate_manual_confirm": 131,
            "multimodal_pending_count": 0,
            "llm_reviewed": False,
            "variant_bundle_present": False,
            "high_risk_cut_count": 0,
        },
        evaluation_risk_snapshot={
            "auto_apply_candidate_count": 2,
            "manual_confirm_candidate_count": 4,
            "rule_auto_apply_cut_count": 92,
            "candidate_risk_summary": {
                "total": {"low": 92, "medium": 3, "high": 1},
                "auto_apply": {"low": 92, "medium": 0, "high": 0},
                "manual_confirm": {"low": 0, "medium": 3, "high": 1},
            },
            "risk_levels": {
                "total": {"low": 92, "medium": 3, "high": 1},
                "auto_apply": {"low": 92, "medium": 0, "high": 0},
                "manual_confirm": {"low": 0, "medium": 3, "high": 1},
            },
            "multimodal_pending_count": 1,
            "llm_reviewed": True,
            "variant_bundle_present": True,
        },
    )

    assert risk_alignment["reference_high_risk_cut_count"] == 0
    assert risk_alignment["reference_expected_source"] == "cut_analysis_refine_decision_plan"
    assert risk_alignment["reference_manual_confirm_candidate_count"] == 131
    assert risk_alignment["reference_auto_apply_candidate_count"] == 0
    assert risk_alignment["fresh_manual_confirm_count"] == 4
    assert risk_alignment["fresh_auto_apply_candidate_count"] == 2
    assert risk_alignment["fresh_multimodal_pending_count"] == 1
    assert risk_alignment["fresh_source"] == "variant_timeline_bundle"
    assert risk_alignment["fresh_rule_auto_apply_cut_count"] == 92
    assert risk_alignment["reference_risk_contract_complete"] is False
    assert risk_alignment["fresh_risk_contract_complete"] is True
    assert risk_alignment["mismatch_codes"] == ["fresh_source_mismatch", "reference_risk_contract_incomplete"]


def test_build_case_risk_alignment_defers_render_stage_high_risk_comparison_for_edit_plan_partial() -> None:
    case = golden.GoldenJobCase(
        case_id="case-render-risk-deferred",
        scenario="render-stage high risk anchor",
        risk_hints={
            "reference_high_risk_cut_count": 1,
            "reference_expected_stage": "render",
            "reference_expected_source": "variant_timeline_bundle",
        },
    )
    report = JobRunReport(
        job_id="job-partial",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="partial",
        output_path="",
        cover_path=None,
        output_duration_sec=0.0,
        transcript_segment_count=1,
        subtitle_count=1,
        correction_count=0,
        keep_ratio=1.0,
        cover_variant_count=0,
        platform_doc=None,
        quality_score=100.0,
        quality_grade="A",
        quality_issue_codes=[],
        live_stage_validations=[
            SimpleNamespace(stage="edit_plan", status="pass", summary="ok"),
            SimpleNamespace(stage="render", status="skipped", summary="render skipped"),
        ],
        content_profile=None,
        steps=[],
        notes=[],
    )

    risk_alignment = golden._build_case_risk_alignment(
        case,
        {
            "editing_risk_metrics": {
                "source": "variant_timeline_bundle",
                "source_reason": "variant_bundle_available",
                "high_risk_cut_count": 0,
                "manual_confirm_count": 0,
                "multimodal_pending_count": 0,
                "llm_reviewed": True,
            }
        },
        report=report,
        reference_risk_snapshot={"high_risk_cut_count": 1, "variant_bundle_present": True},
        evaluation_risk_snapshot={"high_risk_cut_count": 0, "variant_bundle_present": True},
    )

    assert risk_alignment["comparison_deferred"] is True
    assert risk_alignment["comparison_deferred_reason"] == "reference_expected_stage_not_reached:render"
    assert risk_alignment["high_risk_reproduced"] is True
    assert risk_alignment["mismatch_codes"] == []
    assert risk_alignment["status"] == "aligned"


def test_reference_risk_snapshot_restores_rule_auto_apply_and_risk_levels_from_artifacts() -> None:
    case = golden.GoldenJobCase(
        case_id="case-c3-risk-summary",
        scenario="c3 risk summary fallback",
    )
    job = SimpleNamespace(id="job-ref", source_name="demo.mp4")
    latest_by_type = {
        "cut_analysis": SimpleNamespace(
            artifact_type="cut_analysis",
            data_json={
                "candidate_count": 3,
                "accepted_cut_count": 1,
                "rule_candidate_count": 2,
                "auto_apply_candidate_count": 2,
                "manual_confirm_candidate_count": 1,
                "candidate_risk_summary": {
                    "total": {"low": 2, "medium": 1, "high": 0},
                    "auto_apply": {"low": 1, "medium": 0, "high": 0},
                    "manual_confirm": {"low": 1, "medium": 1, "high": 0},
                },
            },
        ),
        "refine_decision_plan": SimpleNamespace(
            artifact_type="refine_decision_plan",
            data_json={
                "rule_auto_apply_cut_count": 1,
                "candidate_summary": {
                    "total": 3,
                    "auto_apply": 2,
                    "manual_confirm": 1,
                    "rule_auto_apply": 1,
                    "multimodal_auto_apply": 1,
                    "risk_levels": {
                        "total": {"low": 2, "medium": 1, "high": 0},
                        "auto_apply": {"low": 1, "medium": 1, "high": 0},
                        "manual_confirm": {"low": 1, "medium": 0, "high": 0},
                    },
                },
            },
        ),
        "multimodal_trim_review": SimpleNamespace(
            artifact_type="multimodal_trim_review",
            data_json={"summary": {"pending_count": 2}},
        ),
        "editorial": SimpleNamespace(
            artifact_type="editorial",
            data_json={"analysis": {"llm_cut_review": {"reviewed": True, "candidate_count": 4}}},
        ),
    }

    snapshot = golden._build_job_risk_snapshot_from_artifacts(
        case_id=case.case_id,
        job=job,
        latest_by_type=latest_by_type,
    )

    assert snapshot["auto_apply_candidate_count"] == 2
    assert snapshot["manual_confirm_candidate_count"] == 1
    assert snapshot["candidate_risk_summary"] == {
        "total": {"low": 2, "medium": 1, "high": 0},
        "auto_apply": {"low": 1, "medium": 0, "high": 0},
        "manual_confirm": {"low": 1, "medium": 1, "high": 0},
    }
    assert snapshot["refine_candidate_manual_confirm"] == 1
    assert snapshot["rule_auto_apply_cut_count"] == 1
    assert snapshot["multimodal_auto_apply_cut_count"] == 1
    assert snapshot["risk_levels"] == {
        "total": {"low": 2, "medium": 1, "high": 0},
        "auto_apply": {"low": 1, "medium": 1, "high": 0},
        "manual_confirm": {"low": 1, "medium": 0, "high": 0},
    }
    assert snapshot["multimodal_pending_count"] == 2
    assert snapshot["llm_reviewed"] is True
    assert snapshot["llm_candidate_count"] == 4


def test_build_case_result_rows_includes_evaluation_risk_snapshot() -> None:
    cases = [
        golden.GoldenJobCase(
            case_id="case-eval-risk",
            scenario="evaluation risk snapshot anchor",
            source_name="demo.mp4",
        ),
    ]
    prepared = [
        golden.PreparedGoldenJob(
            case=cases[0],
            job_id="job-1",
            mode="cloned_full_chain",
            item={"path": "E:/demo.mp4", "source_name": "demo.mp4"},
        ),
    ]
    report = JobRunReport(
        job_id="job-1",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="partial",
        output_path=None,
        cover_path=None,
        output_duration_sec=0.0,
        transcript_segment_count=10,
        subtitle_count=12,
        correction_count=1,
        keep_ratio=0.7,
        cover_variant_count=0,
        platform_doc=None,
        quality_score=82.0,
        quality_grade="B",
        quality_issue_codes=[],
        live_stage_validations=[],
        content_profile=None,
        steps=[StepRun(step="edit_plan", status="done", elapsed_seconds=1.0)],
        notes=[],
    )

    rows = golden.build_case_result_rows(
        cases,
        prepared,
        [report],
        {"jobs": [{"source_name": "demo.mp4", "editing": {"score": 88}, "subtitle_quality": {"score": 87}}]},
        evaluation_risk_snapshots_by_case={
            "case-eval-risk": {
                "case_id": "case-eval-risk",
                "job_id": "job-1",
                "source_name": "demo.mp4",
                "manual_confirm_candidate_count": 6,
                "candidate_risk_summary": {"total": {"low": 2, "medium": 4, "high": 0}},
                "refine_candidate_manual_confirm": 6,
                "rule_auto_apply_cut_count": 1,
                "multimodal_auto_apply_cut_count": 1,
                "risk_levels": {"manual_confirm": {"low": 1, "medium": 5, "high": 0}},
            }
        },
    )

    assert rows[0]["evaluation_risk_snapshot"]["manual_confirm_candidate_count"] == 6
    assert rows[0]["evaluation_risk_snapshot"]["rule_auto_apply_cut_count"] == 1
    assert rows[0]["evaluation_risk_snapshot"]["risk_levels"] == {
        "manual_confirm": {"low": 1, "medium": 5, "high": 0}
    }


def test_build_case_result_rows_marks_all_required_checks_failed_when_report_missing() -> None:
    cases = [
        golden.GoldenJobCase(
            case_id="case-b",
            scenario="missing report anchor",
            source_name="missing.mp4",
            required_checks=["manual_editor_ready", "subtitle_projection"],
        ),
    ]
    rows = golden.build_case_result_rows(
        cases,
        [golden.PreparedGoldenJob(case=cases[0], job_id="job-2", mode="cloned_full_chain", item={"path": "", "source_name": "missing.mp4"})],
        [],
        {"jobs": []},
    )

    assert rows[0]["status"] == "missing"
    assert rows[0]["required_checks_passed"] is False
    assert rows[0]["required_checks_failed"] == ["manual_editor_ready", "subtitle_projection"]


def test_evaluate_required_checks_respects_manual_editor_apply_semantics_gate() -> None:
    case = golden.GoldenJobCase(
        case_id="case-sem",
        scenario="manual editor semantics gate",
        required_checks=["manual_editor_apply_semantics"],
    )

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        manual_editor_apply_semantics={"ok": True},
    )
    assert passed is True
    assert failed == []

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        manual_editor_apply_semantics={"ok": False},
    )
    assert passed is False
    assert failed == ["manual_editor_apply_semantics"]


def test_evaluate_required_checks_prefers_typed_check_statuses_over_stage_names() -> None:
    case = golden.GoldenJobCase(
        case_id="case-typed",
        scenario="typed required checks",
        required_checks=["manual_editor_ready", "subtitle_projection", "cut_analysis_traceability"],
    )

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        check_statuses={
            "manual_editor_ready": {"passed": True},
            "subtitle_projection": {"passed": False},
            "cut_analysis_traceability": {"passed": True},
        },
    )

    assert passed is False
    assert failed == ["subtitle_projection"]


def test_evaluate_required_checks_supports_term_and_low_signal_typed_checks() -> None:
    case = golden.GoldenJobCase(
        case_id="case-typed-extra",
        scenario="typed required checks extra",
        required_checks=["term_format_consistency", "low_signal_traceability"],
    )

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        check_statuses={
            "term_format_consistency": {"passed": True},
            "low_signal_traceability": {"passed": False},
        },
    )

    assert passed is False
    assert failed == ["low_signal_traceability"]


def test_strategy_pipeline_coverage_status_matches_declared_strategy_tag() -> None:
    case = golden.GoldenJobCase(
        case_id="case-strategy",
        scenario="strategy coverage",
        tags=["strategy:information_density"],
    )
    report = JobRunReport(
        job_id="job-strategy",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="partial",
        output_path=None,
        cover_path=None,
        output_duration_sec=0.0,
        transcript_segment_count=0,
        subtitle_count=0,
        correction_count=0,
        keep_ratio=1.0,
        cover_variant_count=0,
        platform_doc=None,
        quality_score=100.0,
        quality_grade="A",
        quality_issue_codes=[],
        live_stage_validations=[],
        content_profile={
            "capability_orchestration": {
                "strategy_type": "information_density",
                "pipeline_plan": {
                    "strategy_type": "information_density",
                },
            }
        },
        steps=[],
        notes=[],
        render_diagnostics={
            "strategy_render_validation": {
                "strategy_type": "information_density",
                "status": "ok",
            }
        },
    )

    status = golden._strategy_pipeline_coverage_status(
        case,
        report=report,
        content_profile_final={},
        strategy_review_gates={},
    )

    assert status["passed"] is True
    assert status["expected_strategy_types"] == ["information_density"]
    assert status["observed_strategy_types"] == ["information_density"]


def test_strategy_pipeline_coverage_status_fails_without_matching_pipeline_evidence() -> None:
    case = golden.GoldenJobCase(
        case_id="case-strategy-missing",
        scenario="strategy coverage missing",
        tags=["strategy:event_highlight"],
    )
    report = JobRunReport(
        job_id="job-strategy",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="partial",
        output_path=None,
        cover_path=None,
        output_duration_sec=0.0,
        transcript_segment_count=0,
        subtitle_count=0,
        correction_count=0,
        keep_ratio=1.0,
        cover_variant_count=0,
        platform_doc=None,
        quality_score=100.0,
        quality_grade="A",
        quality_issue_codes=[],
        live_stage_validations=[],
        content_profile={
            "capability_orchestration": {
                "strategy_type": "information_density",
            }
        },
        steps=[],
        notes=[],
    )

    status = golden._strategy_pipeline_coverage_status(
        case,
        report=report,
        content_profile_final={},
        strategy_review_gates={},
    )

    assert status["passed"] is False
    assert status["missing_strategy_types"] == ["event_highlight"]


def test_evaluate_required_checks_supports_strategy_pipeline_coverage_typed_check() -> None:
    case = golden.GoldenJobCase(
        case_id="case-strategy-check",
        scenario="strategy coverage check",
        tags=["strategy:information_density"],
        required_checks=["strategy_pipeline_coverage"],
    )

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        check_statuses={"strategy_pipeline_coverage": {"passed": True}},
    )

    assert passed is True
    assert failed == []


def test_strategy_boundary_samples_status_passes_with_render_sample_evidence() -> None:
    case = golden.GoldenJobCase(
        case_id="case-event-render",
        scenario="event highlight render",
        tags=["strategy:event_highlight"],
    )
    report = JobRunReport(
        job_id="job-event",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="done",
        output_path="E:/out.mp4",
        cover_path=None,
        output_duration_sec=5.0,
        transcript_segment_count=1,
        subtitle_count=1,
        correction_count=0,
        keep_ratio=0.5,
        cover_variant_count=0,
        platform_doc=None,
        quality_score=90.0,
        quality_grade="A",
        quality_issue_codes=[],
        live_stage_validations=[],
        content_profile=None,
        steps=[],
        notes=[],
        render_diagnostics={
            "strategy_render_validation": {
                "strategy_type": "event_highlight",
                "status": "ok",
                "required": True,
                "boundary_frame_sample_count": 2,
                "boundary_waveform_sample_count": 1,
                "blocking_reasons": [],
            }
        },
    )

    status = golden._strategy_boundary_samples_status(
        case,
        report=report,
        sample_manifest={
            "schema": "strategy_cut_boundary_samples.v1",
            "boundary_samples": [
                {
                    "frame_paths": ["E:/samples/cut_01_01.jpg", "E:/samples/cut_01_02.jpg"],
                    "waveform_path": "E:/samples/cut_01_waveform.json",
                }
            ],
        },
    )

    assert status["passed"] is True
    assert status["strategy_type"] == "event_highlight"
    assert status["frame_sample_count"] == 2
    assert status["waveform_sample_count"] == 1


def test_count_boundary_sample_evidence_does_not_double_count_manifest_totals() -> None:
    frame_count, waveform_count = golden._count_boundary_sample_evidence(
        {
            "frame_count": 1,
            "boundary_samples": [
                {
                    "frame_paths": ["E:/samples/cut_01_01.jpg"],
                    "waveform_path": "E:/samples/cut_01_waveform.json",
                }
            ],
        }
    )

    assert frame_count == 1
    assert waveform_count == 1


def test_strategy_boundary_samples_status_fails_without_render_sample_evidence() -> None:
    case = golden.GoldenJobCase(
        case_id="case-event-render-missing",
        scenario="event highlight render missing samples",
        tags=["strategy:event_highlight"],
    )
    report = JobRunReport(
        job_id="job-event",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="failed",
        output_path=None,
        cover_path=None,
        output_duration_sec=0.0,
        transcript_segment_count=1,
        subtitle_count=1,
        correction_count=0,
        keep_ratio=0.5,
        cover_variant_count=0,
        platform_doc=None,
        quality_score=0.0,
        quality_grade="E",
        quality_issue_codes=["render_failed"],
        live_stage_validations=[],
        content_profile=None,
        steps=[],
        notes=[],
        render_diagnostics={
            "strategy_render_validation": {
                "strategy_type": "event_highlight",
                "status": "blocking",
                "required": True,
                "boundary_frame_sample_count": 0,
                "boundary_waveform_sample_count": 0,
                "blocking_reasons": ["strategy_cut_boundary_frame_samples_missing"],
            }
        },
    )

    status = golden._strategy_boundary_samples_status(
        case,
        report=report,
        sample_manifest={},
    )

    assert status["passed"] is False
    assert "missing_frame_samples" in status["missing_reasons"]
    assert "missing_waveform_samples" in status["missing_reasons"]
    assert "validation_reports_missing_frame_samples" in status["missing_reasons"]


def test_evaluate_required_checks_supports_strategy_boundary_samples_typed_check() -> None:
    case = golden.GoldenJobCase(
        case_id="case-strategy-boundary-check",
        scenario="strategy boundary samples check",
        tags=["strategy:event_highlight"],
        required_checks=["strategy_boundary_samples"],
    )

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        check_statuses={"strategy_boundary_samples": {"passed": True}},
    )

    assert passed is True
    assert failed == []


def test_strategy_review_preview_evidence_status_passes_with_timecoded_preview() -> None:
    case = golden.GoldenJobCase(
        case_id="case-narrative-preview",
        scenario="narrative preview evidence",
        tags=["strategy:narrative_assembly"],
    )

    status = golden._strategy_review_preview_evidence_status(
        case,
        strategy_review_gates={
            "strategy_type": "narrative_assembly",
            "gate_artifacts": {
                "storyboard_review": {"artifact_type": "strategy_storyboard_review"},
                "timeline_preview": {"artifact_type": "strategy_timeline_preview"},
            },
        },
        storyboard_review={
            "strategy_type": "narrative_assembly",
            "panels": [{"panel_id": "opening_hook", "text": "先看关键转折"}],
        },
        timeline_preview={
            "strategy_type": "narrative_assembly",
            "segments": [
                {
                    "segment_id": "preview_1",
                    "timestamp": "00:00-00:04",
                    "text": "插入原始素材解释背景",
                }
            ],
        },
    )

    assert status["passed"] is True
    assert status["storyboard_panel_count"] == 1
    assert status["timeline_segment_count"] == 1
    assert status["timeline_time_anchor_count"] == 1


def test_strategy_review_preview_evidence_status_fails_without_time_anchor() -> None:
    case = golden.GoldenJobCase(
        case_id="case-narrative-preview-missing-time",
        scenario="narrative preview evidence missing time",
        tags=["strategy:narrative_assembly"],
    )

    status = golden._strategy_review_preview_evidence_status(
        case,
        strategy_review_gates={
            "strategy_type": "narrative_assembly",
            "gate_artifacts": {
                "timeline_preview": {"artifact_type": "strategy_timeline_preview"},
            },
        },
        storyboard_review={},
        timeline_preview={
            "strategy_type": "narrative_assembly",
            "segments": [{"segment_id": "preview_1", "text": "缺少时间锚点"}],
        },
    )

    assert status["passed"] is False
    assert "missing_timeline_time_anchors" in status["missing_reasons"]


def test_evaluate_required_checks_supports_strategy_review_preview_evidence_typed_check() -> None:
    case = golden.GoldenJobCase(
        case_id="case-strategy-preview-check",
        scenario="strategy review preview check",
        tags=["strategy:narrative_assembly"],
        required_checks=["strategy_review_preview_evidence"],
    )

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        check_statuses={"strategy_review_preview_evidence": {"passed": True}},
    )

    assert passed is True
    assert failed == []


def test_strategy_review_preview_media_evidence_status_passes_with_readable_source_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"fake media")
    monkeypatch.setattr(golden, "_probe_media_duration_sec", lambda _path: (3.0, ""))
    case = golden.GoldenJobCase(
        case_id="case-narrative-preview-media",
        scenario="narrative preview media evidence",
        source_paths=[str(media_path)],
        tags=["strategy:narrative_assembly"],
    )

    status = golden._strategy_review_preview_media_evidence_status(
        case,
        job=SimpleNamespace(source_path=""),
        strategy_review_gates={"strategy_type": "narrative_assembly"},
        timeline_preview={
            "strategy_type": "narrative_assembly",
            "segments": [
                {
                    "segment_id": "preview_1",
                    "start_time": 0.2,
                    "end_time": 1.5,
                    "text": "插入可核对的素材片段",
                }
            ],
        },
    )

    assert status["passed"] is True
    assert status["source_media_count"] == 1
    assert status["readable_media_count"] == 1
    assert status["media_backed_segment_count"] == 1
    assert status["segment_evidence"][0]["within_media_duration"] is True


def test_strategy_review_preview_media_evidence_resolves_runtime_relative_job_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_media_path = tmp_path / "data" / "runtime" / "jobs" / "job-1" / "source.mp4"
    runtime_media_path.parent.mkdir(parents=True)
    runtime_media_path.write_bytes(b"fake media")
    monkeypatch.setattr(golden, "ROOT", tmp_path)
    monkeypatch.setattr(golden, "_probe_media_duration_sec", lambda _path: (3.0, ""))
    case = golden.GoldenJobCase(
        case_id="case-narrative-preview-media-runtime",
        scenario="narrative preview media evidence with cloned runtime source",
        tags=["strategy:narrative_assembly"],
    )

    status = golden._strategy_review_preview_media_evidence_status(
        case,
        job=SimpleNamespace(source_path="jobs/job-1/source.mp4"),
        strategy_review_gates={"strategy_type": "narrative_assembly"},
        timeline_preview={
            "strategy_type": "narrative_assembly",
            "segments": [{"segment_id": "preview_1", "start_time": 0.2, "end_time": 1.5}],
        },
    )

    assert status["passed"] is True
    assert status["readable_media_count"] == 1
    assert status["media_evidence"][0]["path"] == str(runtime_media_path)


def test_strategy_review_preview_media_evidence_status_fails_when_segments_exceed_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "source.mp4"
    media_path.write_bytes(b"fake media")
    monkeypatch.setattr(golden, "_probe_media_duration_sec", lambda _path: (2.0, ""))
    case = golden.GoldenJobCase(
        case_id="case-narrative-preview-media-outside",
        scenario="narrative preview media evidence outside source",
        source_path=str(media_path),
        tags=["strategy:narrative_assembly"],
    )

    status = golden._strategy_review_preview_media_evidence_status(
        case,
        job=SimpleNamespace(source_path=""),
        strategy_review_gates={"strategy_type": "narrative_assembly"},
        timeline_preview={
            "strategy_type": "narrative_assembly",
            "segments": [{"segment_id": "preview_1", "timestamp": "00:00-00:04"}],
        },
    )

    assert status["passed"] is False
    assert "timeline_segments_outside_media_duration" in status["missing_reasons"]
    assert status["media_backed_segment_count"] == 0


def test_evaluate_required_checks_supports_strategy_review_preview_media_evidence_typed_check() -> None:
    case = golden.GoldenJobCase(
        case_id="case-strategy-preview-media-check",
        scenario="strategy review preview media check",
        tags=["strategy:narrative_assembly"],
        required_checks=["strategy_review_preview_media_evidence"],
    )

    passed, failed = golden._evaluate_required_checks(
        case,
        None,
        check_statuses={"strategy_review_preview_media_evidence": {"passed": True}},
    )

    assert passed is True
    assert failed == []


def test_summarize_strategy_pipeline_coverage_collects_declared_and_missing_strategies() -> None:
    summary = golden.summarize_strategy_pipeline_coverage(
        [
            {
                "case_id": "case-pass",
                "required_check_statuses": {
                    "strategy_pipeline_coverage": {
                        "passed": True,
                        "expected_strategy_types": ["information_density"],
                        "observed_strategy_types": ["information_density"],
                        "missing_strategy_types": [],
                    }
                },
            },
            {
                "case_id": "case-fail",
                "required_check_statuses": {
                    "strategy_pipeline_coverage": {
                        "passed": False,
                        "expected_strategy_types": ["event_highlight"],
                        "observed_strategy_types": ["information_density"],
                        "missing_strategy_types": ["event_highlight"],
                    }
                },
            },
        ]
    )

    assert summary == {
        "evaluated_case_count": 2,
        "declared_strategy_types": ["event_highlight", "information_density"],
        "covered_strategy_types": ["information_density"],
        "missing_strategy_types": ["event_highlight"],
        "failed_case_ids": ["case-fail"],
    }


def test_traceable_cut_candidate_accepts_structured_evidence_without_surface_text() -> None:
    assert golden._traceable_cut_candidate(
        {
            "reason": "rollback_instruction",
            "rule_id": "rollback_instruction:1.000:2.000:",
            "risk_level": "high",
            "match_surface_layer": "raw",
            "signals": ["hard_rule", "spoken_editorial_rollback"],
            "evidence": {"instruction_text": "重来，前面那句不要"},
        }
    )


def test_summarize_required_checks_aggregates_case_level_outcomes() -> None:
    rows = [
        {
            "case_id": "case-pass",
            "required_checks": ["manual_editor_ready", "subtitle_projection"],
            "required_checks_passed": True,
            "required_checks_failed": [],
        },
        {
            "case_id": "case-fail",
            "required_checks": ["manual_editor_ready", "subtitle_projection"],
            "required_checks_passed": False,
            "required_checks_failed": ["subtitle_projection"],
        },
        {
            "case_id": "case-empty",
            "required_checks": [],
            "required_checks_passed": True,
            "required_checks_failed": [],
        },
    ]

    summary = golden.summarize_required_checks(rows)

    assert summary["required_checks_total"] == 4
    assert summary["required_checks_contract_passed"] == 3
    assert summary["required_checks_contract_failed"] == 1
    assert summary["required_checks_case_passed"] == 1
    assert summary["required_checks_case_failed"] == 1
    assert summary["required_checks_failed_case_ids"] == ["case-fail"]
    assert summary["cases_with_checks"] == 2
    assert abs(summary["required_checks_contract_pass_rate"] - 0.75) < 1e-9


def test_model_token_integrity_status_passes_when_profile_matches_source_identity() -> None:
    status = golden._model_token_integrity_status(
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        content_profile={
            "subject_brand": "NITECORE",
            "subject_model": "EDC17",
            "subject_type": "EDC手电",
        },
        quality_issue_codes=set(),
    )

    assert status["passed"] is True
    assert status["expected_brand"] == "NITECORE"
    assert status["expected_model"] == "EDC17"
    assert status["mismatch_fields"] == []
    assert status["missing_fields"] == []


def test_model_token_integrity_status_fails_when_profile_conflicts_with_source_identity() -> None:
    status = golden._model_token_integrity_status(
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        content_profile={
            "subject_brand": "NITECORE",
            "subject_model": "EDC37",
            "subject_type": "EDC手电",
        },
        quality_issue_codes={"identity_narrative_conflict"},
    )

    assert status["passed"] is False
    assert status["mismatch_fields"] == ["subject_model"]
    assert status["issue_codes"] == ["identity_narrative_conflict"]


def test_term_format_consistency_status_fails_when_terms_are_pending() -> None:
    status = golden._term_format_consistency_status(
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        content_profile={
            "subject_brand": "NITECORE",
            "subject_model": "EDC17",
            "subject_type": "EDC手电",
        },
        quality_issue_codes={"subtitle_terms_pending"},
    )

    assert status["passed"] is False
    assert status["issue_codes"] == ["subtitle_terms_pending"]
    assert "subtitle_terms_pending" in status["detail"]


def test_low_signal_traceability_status_requires_traceable_low_signal_candidates() -> None:
    passed = golden._low_signal_traceability_status(
        {
            "accepted_cuts": [
                {
                    "reason": "low_signal_subtitle",
                    "rule_id": "low_signal_subtitle:0.000:0.800:然后呢",
                    "risk_level": "medium",
                    "match_surface_layer": "canonical",
                    "source_text": "然后呢",
                }
            ],
            "rule_candidates": [],
        }
    )
    failed = golden._low_signal_traceability_status(
        {
            "accepted_cuts": [
                {
                    "reason": "low_signal_subtitle",
                    "rule_id": "low_signal_subtitle:0.000:0.800:",
                    "risk_level": "medium",
                    "match_surface_layer": "",
                    "source_text": "",
                }
            ],
            "rule_candidates": [],
        }
    )

    assert passed["passed"] is True
    assert passed["target_count"] == 1
    assert failed["passed"] is False
    assert failed["missing_count"] == 1


def test_subtitle_projection_required_check_allows_projection_warnings_without_failing_availability() -> None:
    status = golden._subtitle_projection_required_check_status(
        {"entries": [{"index": 0}]},
        {"canonical_projection_quality_warning"},
    )

    assert status["passed"] is True
    assert status["issue_codes"] == []
    assert status["warning_codes"] == ["canonical_projection_quality_warning"]


def test_subtitle_projection_required_check_still_fails_on_blocking_projection_issues() -> None:
    status = golden._subtitle_projection_required_check_status(
        {"entries": [{"index": 0}]},
        {"canonical_projection_quality_blocking", "subtitle_semantic_contamination"},
    )

    assert status["passed"] is False
    assert status["issue_codes"] == [
        "canonical_projection_quality_blocking",
        "subtitle_semantic_contamination",
    ]


def test_summarize_manual_editor_apply_semantics_aggregates_case_level_outcomes() -> None:
    rows = [
        {
            "case_id": "case-pass",
            "required_checks": ["manual_editor_apply_semantics"],
            "manual_editor_apply_semantics_ok": True,
        },
        {
            "case_id": "case-fail",
            "required_checks": ["manual_editor_apply_semantics"],
            "manual_editor_apply_semantics_ok": False,
        },
    ]

    summary = golden.summarize_manual_editor_apply_semantics(rows)

    assert summary == {
        "total_cases": 2,
        "passed_case_count": 1,
        "failed_case_count": 1,
        "failed_case_ids": ["case-fail"],
        "pass_rate": 0.5,
    }


def test_summarize_manual_editor_apply_semantics_ignores_cases_without_required_check() -> None:
    rows = [
        {
            "case_id": "case-semantic-pass",
            "required_checks": ["manual_editor_apply_semantics"],
            "manual_editor_apply_semantics_ok": True,
        },
        {
            "case_id": "case-non-semantic-fail",
            "required_checks": ["subtitle_projection"],
            "manual_editor_apply_semantics_ok": False,
        },
    ]

    summary = golden.summarize_manual_editor_apply_semantics(rows)

    assert summary == {
        "total_cases": 1,
        "passed_case_count": 1,
        "failed_case_count": 0,
        "failed_case_ids": [],
        "pass_rate": 1.0,
    }


def test_summarize_render_diagnostics_aggregates_failed_and_degraded_jobs() -> None:
    reports = [
        JobRunReport(
            job_id="job-fail",
            source_path="E:/a.mp4",
            source_name="a.mp4",
            status="failed",
            output_path=None,
            cover_path=None,
            output_duration_sec=0.0,
            transcript_segment_count=0,
            subtitle_count=0,
            correction_count=0,
            keep_ratio=0.0,
            cover_variant_count=0,
            platform_doc=None,
            quality_score=None,
            quality_grade=None,
            quality_issue_codes=[],
            live_stage_validations=[],
            content_profile=None,
            steps=[],
            notes=[],
            render_diagnostics={
                "render_step": {"status": "failed", "reason": "render_failed"},
                "cover_result": {"status": "degraded", "reason": "cover_export_failed"},
            },
        ),
        JobRunReport(
            job_id="job-avatar",
            source_path="E:/b.mp4",
            source_name="b.mp4",
            status="done",
            output_path="E:/b_out.mp4",
            cover_path="E:/b_cover.png",
            output_duration_sec=6.0,
            transcript_segment_count=3,
            subtitle_count=4,
            correction_count=0,
            keep_ratio=0.5,
            cover_variant_count=1,
            platform_doc=None,
            quality_score=88.0,
            quality_grade="B",
            quality_issue_codes=[],
            live_stage_validations=[],
            content_profile=None,
            steps=[],
            notes=[],
            render_diagnostics={
                "render_step": {"status": "done"},
                "avatar_result": {
                    "status": "degraded",
                    "reason": "avatar_full_track_call_timeout",
                    "reason_category": "call_timeout",
                },
            },
        ),
    ]

    summary = golden.summarize_render_diagnostics(reports)

    assert summary == {
        "evaluated_job_count": 2,
        "failed_render_job_count": 1,
        "failed_render_job_ids": ["job-fail"],
        "failed_render_reasons": {"render_failed": 1},
        "cover_degraded_job_count": 0,
        "cover_degraded_job_ids": [],
        "cover_degraded_reasons": {},
        "avatar_degraded_job_count": 1,
        "avatar_degraded_job_ids": ["job-avatar"],
        "avatar_degraded_reasons": {"avatar_full_track_call_timeout": 1},
        "avatar_degraded_reason_categories": {"call_timeout": 1},
        "strategy_validation_evaluated_job_count": 0,
        "strategy_validation_blocking_job_count": 0,
        "strategy_validation_blocking_job_ids": [],
        "strategy_validation_blocking_reasons": {},
        "strategy_validation_strategy_types": {},
        "strategy_validation_review_gates": {},
    }


def test_summarize_render_diagnostics_aggregates_strategy_validation() -> None:
    summary = golden.summarize_render_diagnostics(
        [
            JobRunReport(
                job_id="job-strategy",
                source_path="E:/demo.mp4",
                source_name="demo.mp4",
                status="done",
                output_path="E:/out.mp4",
                cover_path=None,
                output_duration_sec=12.0,
                transcript_segment_count=0,
                subtitle_count=0,
                correction_count=0,
                keep_ratio=1.0,
                cover_variant_count=0,
                platform_doc=None,
                quality_score=90.0,
                quality_grade="A",
                quality_issue_codes=[],
                live_stage_validations=[],
                content_profile=None,
                steps=[],
                notes=[],
                render_diagnostics={
                    "strategy_render_validation": {
                        "status": "blocking",
                        "reason": "strategy_timeline_preview_missing",
                        "blocking_reasons": [
                            "strategy_timeline_preview_missing",
                            "strategy_storyboard_review_missing",
                        ],
                        "strategy_type": "narrative_assembly",
                        "review_gates": ["timeline_preview_required", "storyboard_review_required"],
                        "blocking": True,
                    }
                },
            )
        ]
    )

    assert summary["strategy_validation_evaluated_job_count"] == 1
    assert summary["strategy_validation_blocking_job_count"] == 1
    assert summary["strategy_validation_blocking_job_ids"] == ["job-strategy"]
    assert summary["strategy_validation_blocking_reasons"] == {
        "strategy_storyboard_review_missing": 1,
        "strategy_timeline_preview_missing": 1,
    }
    assert summary["strategy_validation_strategy_types"] == {"narrative_assembly": 1}
    assert summary["strategy_validation_review_gates"] == {
        "storyboard_review_required": 1,
        "timeline_preview_required": 1,
    }


def test_summarize_render_outputs_preserves_avatar_failure_payload() -> None:
    summary = summarize_render_outputs(
        [
            {"artifact_type": "content_profile", "data_json": {"summary": "ignore"}},
            {
                "artifact_type": "render_outputs",
                "data_json": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "avatar_full_track_slot_timeout",
                        "detail": "slot wait timeout",
                        "retryable": True,
                        "error_metadata": {"slot_timeout_seconds": 120.0},
                    },
                    "cover": "E:/cover.png",
                },
            },
        ]
    )

    assert summary == {
        "avatar_result": {
            "status": "degraded",
            "reason": "avatar_full_track_slot_timeout",
            "reason_category": "slot_timeout",
            "detail": "slot wait timeout",
            "retryable": True,
            "error_metadata": {"slot_timeout_seconds": 120.0},
        },
    }


def test_summarize_render_outputs_prefers_runtime_avatar_reason_and_adds_category() -> None:
    summary = summarize_render_outputs(
        [
            {
                "artifact_type": "render_runtime_diagnostics",
                "data_json": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "avatar_full_track_call_timeout",
                        "detail": "call timeout",
                        "retryable": True,
                        "error_metadata": {"call_timeout_seconds": 180.0},
                    }
                },
            },
            {
                "artifact_type": "render_outputs",
                "data_json": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "missing_avatar_render",
                        "detail": "fallback plain render",
                    },
                    "cover": "E:/cover.png",
                },
            },
        ]
    )

    assert summary["avatar_result"] == {
        "status": "degraded",
        "reason": "avatar_full_track_call_timeout",
        "reason_category": "call_timeout",
        "detail": "call timeout",
        "retryable": True,
        "error_metadata": {"call_timeout_seconds": 180.0},
    }
    assert "cover" not in summary


def test_summarize_render_outputs_preserves_strategy_validation_payload() -> None:
    summary = summarize_render_outputs(
        [
            {
                "artifact_type": "render_runtime_diagnostics",
                "data_json": {
                    "strategy_render_validation": {
                        "schema": "strategy_render_validation.v1",
                        "check": "strategy_timeline_preview_alignment",
                        "status": "blocking",
                        "reason": "strategy_timeline_preview_missing",
                        "strategy_type": "narrative_assembly",
                        "required": True,
                        "blocking": True,
                        "segment_count": 0,
                        "panel_count": 0,
                        "overlay_count": 1,
                        "unsafe_overlay_count": 1,
                        "blocking_reasons": [
                            "strategy_timeline_preview_missing",
                            "strategy_storyboard_review_missing",
                            "strategy_overlay_subtitle_occlusion_unverified",
                        ],
                        "checks": [
                            {
                                "check": "strategy_timeline_preview_alignment",
                                "status": "blocking",
                            },
                            {
                                "check": "strategy_storyboard_alignment",
                                "status": "blocking",
                            },
                            {
                                "check": "strategy_overlay_subtitle_occlusion",
                                "status": "blocking",
                            },
                        ],
                        "review_gates": ["timeline_preview_required"],
                    }
                },
            }
        ]
    )

    assert summary["strategy_render_validation"] == {
        "schema": "strategy_render_validation.v1",
        "check": "strategy_timeline_preview_alignment",
        "status": "blocking",
        "reason": "strategy_timeline_preview_missing",
        "strategy_type": "narrative_assembly",
        "required": True,
        "blocking": True,
        "segment_count": 0,
        "panel_count": 0,
        "overlay_count": 1,
        "unsafe_overlay_count": 1,
        "blocking_reasons": [
            "strategy_timeline_preview_missing",
            "strategy_storyboard_review_missing",
            "strategy_overlay_subtitle_occlusion_unverified",
        ],
        "checks": [
            {
                "check": "strategy_timeline_preview_alignment",
                "status": "blocking",
            },
            {
                "check": "strategy_storyboard_alignment",
                "status": "blocking",
            },
            {
                "check": "strategy_overlay_subtitle_occlusion",
                "status": "blocking",
            },
        ],
        "review_gates": ["timeline_preview_required"],
    }


def test_summarize_render_outputs_ignores_runtime_cover_payload() -> None:
    summary = summarize_render_outputs(
        [
            {
                "artifact_type": "render_runtime_diagnostics",
                "data_json": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "avatar_full_track_call_timeout",
                        "detail": "call timeout",
                        "retryable": True,
                        "error_metadata": {"call_timeout_seconds": 180.0},
                    },
                    "cover_result": {
                        "status": "done",
                        "detail": "cover generated",
                        "cover_path": "E:/cover.png",
                        "variant_count": 5,
                    },
                },
            }
        ]
    )

    assert summary == {
        "avatar_result": {
            "status": "degraded",
            "reason": "avatar_full_track_call_timeout",
            "reason_category": "call_timeout",
            "detail": "call timeout",
            "retryable": True,
            "error_metadata": {"call_timeout_seconds": 180.0},
        },
    }


def test_normalize_render_outputs_summary_for_reporting_adds_avatar_reason_category() -> None:
    summary = _normalize_render_outputs_summary_for_reporting(
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_provider_response_error",
                "detail": "provider error",
            }
        },
        [],
    )

    assert summary["avatar_result"]["reason_category"] == "provider_error"


def test_build_audit_markdown_includes_render_outputs_summary() -> None:
    content = build_audit_markdown(
        {
            "job": {
                "id": "job-1",
                "source_name": "demo.mp4",
                "status": "failed",
                "stored_status": "failed",
                "source_path": "E:/demo.mp4",
                "error_message": "render failed",
                "located_paths": [],
            },
            "artifacts": {
                "counts": {"render_outputs": 1},
                "active_profile_type": None,
                "active_profile_summary": {},
                "render_outputs_summary": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "avatar_full_track_provider_response_error",
                        "reason_category": "provider_error",
                        "detail": "provider error",
                        "retryable": False,
                    }
                },
            },
            "step_status": [],
            "transcript_hits": [],
            "subtitle_hits": [],
            "heuristics": {"issues": []},
        },
        {},
    )

    assert "render outputs summary" in content
    assert "avatar_full_track_provider_response_error" in content
    assert "\"reason_category\": \"provider_error\"" in content


def test_build_audit_markdown_prefers_failed_render_root_cause_over_missing_avatar_render() -> None:
    content = build_audit_markdown(
        {
            "job": {
                "id": "job-timeout",
                "source_name": "demo.mp4",
                "status": "failed",
                "stored_status": "failed",
                "source_path": "E:/demo.mp4",
                "error_message": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                "located_paths": [],
            },
            "artifacts": {
                "counts": {"render_runtime_diagnostics": 1},
                "active_profile_type": None,
                "active_profile_summary": {},
                "render_outputs_summary": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "missing_avatar_render",
                        "detail": "没有拿到可用数字人视频，已自动回退普通成片。",
                    }
                },
            },
            "step_status": [
                {
                    "step_name": "render",
                    "status": "failed",
                    "attempt": 3,
                    "started_at": "",
                    "finished_at": "",
                    "detail": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                    "error": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                    "sync_runner": {
                        "sync_runner_timeout_strategy": "process",
                        "sync_runner_timeout_seconds": 300.0,
                    },
                }
            ],
            "transcript_hits": [],
            "subtitle_hits": [],
            "heuristics": {"issues": []},
        },
        {},
    )

    assert "\"reason\": \"render_timeout_process\"" in content
    assert "\"status\": \"blocked\"" in content
    assert "missing_avatar_render" not in content


def test_build_audit_markdown_prefers_ffmpeg_render_root_cause_over_missing_avatar_render() -> None:
    content = build_audit_markdown(
        {
            "job": {
                "id": "job-ffmpeg",
                "source_name": "demo.mp4",
                "status": "failed",
                "stored_status": "failed",
                "source_path": "E:/demo.mp4",
                "error_message": "FFmpeg render failed: filter graph error",
                "located_paths": [],
            },
            "artifacts": {
                "counts": {"render_runtime_diagnostics": 1},
                "active_profile_type": None,
                "active_profile_summary": {},
                "render_outputs_summary": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "missing_avatar_render",
                        "detail": "没有拿到可用数字人视频，已自动回退普通成片。",
                    }
                },
            },
            "step_status": [
                {
                    "step_name": "render",
                    "status": "failed",
                    "attempt": 3,
                    "started_at": "",
                    "finished_at": "",
                    "detail": "FFmpeg render failed: filter graph error",
                    "error": "FFmpeg render failed: filter graph error",
                    "sync_runner": {},
                }
            ],
            "transcript_hits": [],
            "subtitle_hits": [],
            "heuristics": {"issues": []},
        },
        {},
    )

    assert "\"reason\": \"ffmpeg_render_failed\"" in content
    assert "\"status\": \"blocked\"" in content
    assert "missing_avatar_render" not in content


def test_build_audit_markdown_synthesizes_blocked_render_summary_when_avatar_result_missing() -> None:
    content = build_audit_markdown(
        {
            "job": {
                "id": "job-render-only-timeout",
                "source_name": "demo.mp4",
                "status": "failed",
                "stored_status": "failed",
                "source_path": "E:/demo.mp4",
                "error_message": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                "located_paths": [],
            },
            "artifacts": {
                "counts": {},
                "active_profile_type": None,
                "active_profile_summary": {},
                "render_outputs_summary": {},
            },
            "step_status": [
                {
                    "step_name": "render",
                    "status": "failed",
                    "attempt": 3,
                    "started_at": "",
                    "finished_at": "",
                    "detail": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                    "error": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                    "sync_runner": {
                        "sync_runner_timeout_strategy": "process",
                        "sync_runner_timeout_seconds": 300.0,
                    },
                }
            ],
            "transcript_hits": [],
            "subtitle_hits": [],
            "heuristics": {"issues": []},
        },
        {},
    )

    assert "\"reason\": \"render_timeout_process\"" in content
    assert "\"status\": \"blocked\"" in content


def test_merge_historical_render_context_restores_failed_timeout_evidence() -> None:
    status, error, step_rows, summary = _merge_historical_render_context(
        effective_status="processing",
        effective_error="",
        step_rows=[
            {
                "step_name": "render",
                "status": "cancelled",
                "attempt": 3,
                "started_at": "",
                "finished_at": "",
                "detail": "任务到达时作业已终止，当前步骤已停止。",
                "error": "",
                "sync_runner": {},
            }
        ],
        render_outputs_summary={},
        historical_render_diagnostics={
            "avatar_result": {
                "status": "degraded",
                "reason": "missing_avatar_render",
                "detail": "没有拿到可用数字人视频，已自动回退普通成片。",
            },
            "render_step": {
                "status": "failed",
                "detail": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                "error": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                "reason": "render_failed",
                "sync_runner": {
                    "sync_runner_timeout_strategy": "process",
                    "sync_runner_timeout_seconds": 300.0,
                },
            },
        },
    )

    assert status == "failed"
    assert error == "TimeoutError: 步骤 render 执行超过 300.0 秒"
    assert step_rows[0]["status"] == "failed"
    assert step_rows[0]["error"] == "TimeoutError: 步骤 render 执行超过 300.0 秒"
    assert step_rows[0]["sync_runner"] == {
        "sync_runner_timeout_strategy": "process",
        "sync_runner_timeout_seconds": 300.0,
    }
    assert summary["avatar_result"]["reason"] == "missing_avatar_render"


def test_render_case_summary_markdown_includes_manual_editor_apply_semantics() -> None:
    content = golden.render_case_summary_markdown(
        manifest_path=Path("E:/manifest.json"),
        case_rows=[
            {
                "case_id": "case-a",
                "scenario": "manual editor anchor",
                "source_name": "demo.mp4",
                "reference_job_id": "job-ref",
                "evaluation_job_id": "job-eval",
                "evaluation_mode": "cloned_full_chain",
                "status": "done",
                "quality_grade": "A",
                "quality_score": 90.0,
                "subtitle_quality_score": 88,
                "editing_score": 89,
                "manual_editor_ready": True,
                "manual_editor_apply_semantics_ok": True,
                "manual_editor_managed_auto_cut_count": 5,
                "manual_editor_change_scope": "subtitle_only",
                "manual_editor_timeline_changed": False,
                "manual_editor_render_strategy": "reuse_timeline_effect_plan",
                "manual_editor_roundtrip_matches_editorial": True,
                "manual_editor_session_baseline_matches_restored": True,
                "required_checks_passed": True,
                "required_checks": ["manual_editor_apply_semantics"],
                "required_checks_failed": [],
                "tags": ["manual_editor"],
                "notes": "",
                "risk_hints": {
                    "reference_high_risk_cut_count": 3,
                    "reference_expected_stage": "render",
                    "fresh_expectations": {
                        "edit_plan": {
                            "expected_source": "variant_timeline_bundle",
                            "manual_confirm_hint": 7,
                        }
                    },
                },
                "risk_alignment": {
                    "reference_high_risk_cut_count": 3,
                    "reference_expected_stage": "render",
                    "reference_expected_source": "variant_timeline_bundle",
                    "reference_llm_reviewed": False,
                    "reference_manual_confirm_candidate_count": 0,
                    "reference_multimodal_pending_count": 0,
                    "fresh_high_risk_cut_count": 0,
                    "fresh_source": "variant_timeline_bundle",
                    "fresh_source_reason": "variant_bundle_available",
                    "fresh_manual_confirm_count": 7,
                    "fresh_multimodal_pending_count": 0,
                    "fresh_llm_reviewed": True,
                    "high_risk_reproduced": False,
                    "mismatch_codes": ["reference_high_risk_not_reproduced"],
                    "status": "mismatch",
                },
                "reference_risk_snapshot": {
                    "job_id": "job-ref",
                    "source_name": "demo.mp4",
                    "artifact_types": ["render_outputs", "variant_timeline_bundle"],
                    "variant_bundle_present": True,
                    "has_render_outputs": True,
                    "has_cut_analysis": False,
                    "high_risk_cut_count": 3,
                    "manual_confirm_candidate_count": 0,
                    "refine_candidate_manual_confirm": 0,
                    "multimodal_pending_count": 0,
                    "llm_reviewed": False,
                    "llm_candidate_count": 3,
                    "llm_error": "llm_cut_review_failed",
                    "review_recommended": True,
                    "review_reasons": ["check boundaries"],
                    "first_high_risk_cut_reason": "silence",
                },
            }
        ],
        required_checks_summary={
            "required_checks_contract_passed": 1,
            "required_checks_total": 1,
            "required_checks_case_failed": 0,
            "cases_with_checks": 1,
        },
        strategy_pipeline_coverage_summary={
            "evaluated_case_count": 1,
            "declared_strategy_types": ["information_density"],
            "covered_strategy_types": ["information_density"],
            "missing_strategy_types": [],
            "failed_case_ids": [],
        },
        render_diagnostics_summary={
            "evaluated_job_count": 1,
            "failed_render_job_count": 1,
            "cover_degraded_job_count": 0,
            "avatar_degraded_job_count": 1,
            "failed_render_reasons": {"render_failed": 1},
            "avatar_degraded_reasons": {"avatar_full_track_call_timeout": 1},
            "avatar_degraded_reason_categories": {"call_timeout": 1},
        },
        risk_alignment_summary={
            "reference_high_risk_case_count": 1,
            "reproduced_case_count": 0,
            "unreproduced_case_count": 1,
            "mismatch_code_counts": {"reference_high_risk_not_reproduced": 1},
        },
        reference_refresh_candidates=[],
        batch_report_path=Path("E:/batch_report.json"),
        scorecard_path=Path("E:/scorecard.json"),
        audit_paths={},
    )

    assert "## Render Diagnostics Summary" in content
    assert "## Strategy Pipeline Coverage" in content
    assert "covered_strategy_types: information_density" in content
    assert "## Risk Alignment Summary" in content
    assert "failed_render_reasons: render_failed=1" in content
    assert "avatar_degraded_reasons: avatar_full_track_call_timeout=1" in content
    assert "avatar_degraded_reason_categories: call_timeout=1" in content
    assert "mismatch_codes: reference_high_risk_not_reproduced=1" in content
    assert "manual_editor_apply_semantics_ok: True" in content
    assert "manual_editor_apply: change_scope=subtitle_only / timeline_changed=False / render_strategy=reuse_timeline_effect_plan" in content
    assert "reference_high_risk_cut_count: 3" in content
    assert "reference_expected_stage: render" in content
    assert "fresh_expectations:" in content
    assert "edit_plan:" in content
    assert "expected_source: variant_timeline_bundle" in content
    assert "manual_confirm_hint: 7" in content
    assert "reference_risk_snapshot:" in content
    assert "llm_error: llm_cut_review_failed" in content
    assert "risk_alignment:" in content
    assert "fresh_high_risk_cut_count: 0" in content
    assert "fresh_llm_reviewed: True" in content
    assert "reference_llm_reviewed: False" in content
    assert "status: mismatch" in content


def test_render_case_summary_markdown_includes_reference_refresh_candidates() -> None:
    content = golden.render_case_summary_markdown(
        manifest_path=Path("E:/manifest.json"),
        case_rows=[],
        required_checks_summary={
            "required_checks_contract_passed": 0,
            "required_checks_total": 0,
            "required_checks_case_failed": 0,
            "cases_with_checks": 0,
        },
        strategy_pipeline_coverage_summary=None,
        render_diagnostics_summary=None,
        risk_alignment_summary=None,
        reference_refresh_candidates=[
            {
                "case_id": "case-refresh",
                "reference_job_id": "job-ref",
                "evaluation_job_id": "job-eval",
                "fresh_rule_auto_apply_cut_count": 92,
                "fresh_manual_confirm_count": 4,
                "mismatch_codes": ["reference_risk_contract_incomplete"],
            }
        ],
        batch_report_path=Path("E:/batch_report.json"),
        scorecard_path=Path("E:/scorecard.json"),
        audit_paths={},
    )

    assert "## Reference Refresh Candidates" in content
    assert "candidate_count: 1" in content
    assert "case-refresh:" in content
    assert "fresh_rule_auto_apply_cut_count: 92" in content
    assert "mismatch_codes: reference_risk_contract_incomplete" in content


def test_collect_manual_editor_apply_semantics_prefers_evaluation_job_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    case = golden.GoldenJobCase(
        case_id="case-a",
        scenario="manual editor boundary",
        source_name="reference.mp4",
        reference_job_id="job-ref",
    )
    prepared = golden.PreparedGoldenJob(
        case=case,
        job_id="job-eval",
        mode="cloned_full_chain",
        item={"path": "E:/eval.mp4", "source_name": "eval.mp4"},
    )

    async def fake_inspect(case_arg, *, job_id="", source_name=""):
        return {
            "case_id": case_arg.case_id,
            "job_id": job_id,
            "source_name": source_name,
            "managed_auto_cut_count": 2,
            "ok": True,
        }

    monkeypatch.setattr(golden, "inspect_manual_editor_apply_semantics", fake_inspect)

    result = asyncio.run(golden.collect_manual_editor_apply_semantics([case], [prepared]))

    assert result == {
        "case-a": {
            "case_id": "case-a",
            "job_id": "job-eval",
            "source_name": "eval.mp4",
            "managed_auto_cut_count": 2,
            "ok": True,
        }
    }


def test_manual_editor_apply_semantics_payload_reuses_subtitle_only_contract() -> None:
    payload = golden._manual_editor_apply_semantics_payload(
        {
            "change_scope": "subtitle_only",
            "render_strategy": "reuse_timeline_effect_plan",
            "timeline_changed": False,
            "subtitle_changed": True,
            "video_transform_changed": False,
            "rotation_changed": False,
        },
        session_baseline_matches_restored=True,
        roundtrip_matches_editorial=True,
    )

    assert payload["ok"] is True
    assert payload["change_scope"] == "subtitle_only"
    assert payload["render_strategy"] == "reuse_timeline_effect_plan"
    assert payload["rerun_start_step"] == "render"
    assert payload["rerun_steps"] == ["render"]


def test_manual_editor_apply_semantics_payload_keeps_no_material_change_rerun_shrunk() -> None:
    payload = golden._manual_editor_apply_semantics_payload(
        {
            "change_scope": "no_material_change",
            "render_strategy": "metadata_refresh_render",
            "timeline_changed": False,
            "subtitle_changed": False,
            "video_transform_changed": False,
            "rotation_changed": False,
        },
        session_baseline_matches_restored=True,
        roundtrip_matches_editorial=True,
    )

    assert payload["ok"] is True
    assert payload["change_scope"] == "no_material_change"
    assert payload["render_strategy"] == "metadata_refresh_render"
    assert payload["rerun_start_step"] == ""
    assert payload["rerun_steps"] == []


def test_manual_editor_apply_semantics_payload_rejects_inconsistent_contract() -> None:
    payload = golden._manual_editor_apply_semantics_payload(
        {
            "change_scope": "subtitle_only",
            "render_strategy": "metadata_refresh_render",
            "timeline_changed": False,
            "subtitle_changed": True,
            "video_transform_changed": False,
            "rotation_changed": False,
        },
        session_baseline_matches_restored=True,
        roundtrip_matches_editorial=True,
    )

    assert payload["ok"] is False


def test_build_case_result_rows_includes_risk_alignment_summary() -> None:
    case = golden.GoldenJobCase(
        case_id="noc_mt34_short_done",
        scenario="high risk anchor",
        reference_job_id="job-ref",
        risk_hints={
            "reference_high_risk_cut_count": 1,
            "reference_expected_stage": "render",
            "reference_expected_source": "variant_timeline_bundle",
        },
    )
    prepared = golden.PreparedGoldenJob(case=case, job_id="job-eval", mode="cloned_full_chain", item={})
    report = JobRunReport(
        job_id="job-eval",
        source_path="E:/demo.mp4",
        source_name="demo.mp4",
        status="done",
        output_path="E:/out.mp4",
        cover_path=None,
        output_duration_sec=1.0,
        transcript_segment_count=1,
        subtitle_count=1,
        correction_count=0,
        keep_ratio=0.5,
        cover_variant_count=0,
        platform_doc=None,
        quality_score=80.0,
        quality_grade="B",
        quality_issue_codes=[],
        live_stage_validations=[],
        content_profile=None,
        steps=[],
        notes=[],
    )
    scorecard = {
        "jobs": [
            {
                "source_name": "demo.mp4",
                "editing": {"score": 70.0},
                "subtitle_quality": {"score": 90.0},
                "editing_risk_metrics": {
                    "source": "legacy_editorial_cut_analysis",
                    "source_reason": "pre_render_stop_without_variant_bundle",
                    "high_risk_cut_count": 0,
                    "manual_confirm_count": 7,
                    "multimodal_pending_count": 4,
                    "llm_reviewed": True,
                },
            }
        ]
    }

    rows = golden.build_case_result_rows([case], [prepared], [report], scorecard)

    assert len(rows) == 1
    risk_alignment = rows[0]["risk_alignment"]
    assert risk_alignment == {
        "reference_high_risk_cut_count": 1,
        "reference_expected_stage": "render",
        "reference_expected_source": "variant_timeline_bundle",
        "reference_llm_reviewed": False,
        "reference_manual_confirm_candidate_count": 0,
        "reference_multimodal_pending_count": 0,
        "reference_auto_apply_candidate_count": 0,
        "reference_rule_auto_apply_cut_count": 0,
        "reference_candidate_risk_summary": {},
        "reference_risk_levels": {},
        "reference_risk_contract_complete": False,
        "fresh_high_risk_cut_count": 0,
        "fresh_source": "legacy_editorial_cut_analysis",
        "fresh_source_reason": "pre_render_stop_without_variant_bundle",
        "fresh_manual_confirm_count": 7,
        "fresh_multimodal_pending_count": 4,
        "fresh_llm_reviewed": True,
        "fresh_auto_apply_candidate_count": 0,
        "fresh_rule_auto_apply_cut_count": 0,
        "fresh_candidate_risk_summary": {},
        "fresh_risk_levels": {},
        "fresh_risk_contract_complete": False,
        "high_risk_reproduced": False,
        "comparison_deferred": False,
        "comparison_deferred_reason": None,
        "mismatch_codes": ["reference_high_risk_not_reproduced", "fresh_source_mismatch"],
        "status": "mismatch",
    }

    summary = golden.summarize_case_risk_alignment(rows)
    assert summary == {
        "reference_high_risk_case_count": 1,
        "reproduced_case_count": 0,
        "unreproduced_case_count": 1,
        "mismatch_case_ids": ["noc_mt34_short_done"],
        "mismatch_code_counts": {
            "reference_high_risk_not_reproduced": 1,
            "fresh_source_mismatch": 1,
        },
    }


def test_summarize_case_risk_alignment_skips_deferred_render_stage_comparisons() -> None:
    summary = golden.summarize_case_risk_alignment(
        [
            {
                "case_id": "case-deferred",
                "risk_alignment": {
                    "reference_high_risk_cut_count": 1,
                    "comparison_deferred": True,
                    "high_risk_reproduced": True,
                    "mismatch_codes": [],
                },
            }
        ]
    )

    assert summary == {
        "reference_high_risk_case_count": 0,
        "reproduced_case_count": 0,
        "unreproduced_case_count": 0,
        "mismatch_case_ids": [],
        "mismatch_code_counts": {},
    }


def test_summarize_reference_refresh_candidates_extracts_actionable_rows() -> None:
    rows = [
        {
            "case_id": "case-refresh",
            "scenario": "refresh me",
            "reference_job_id": "job-ref",
            "evaluation_job_id": "job-eval",
            "evaluation_mode": "cloned_profile_only",
            "evaluation_risk_snapshot": {"job_id": "job-eval"},
            "risk_alignment": {
                "reference_expected_source": "cut_analysis_refine_decision_plan",
                "fresh_source": "variant_timeline_bundle",
                "reference_auto_apply_candidate_count": 0,
                "fresh_auto_apply_candidate_count": 2,
                "reference_rule_auto_apply_cut_count": 0,
                "fresh_rule_auto_apply_cut_count": 92,
                "reference_manual_confirm_candidate_count": 131,
                "fresh_manual_confirm_count": 4,
                "fresh_multimodal_pending_count": 1,
                "fresh_high_risk_cut_count": 1,
                "fresh_llm_reviewed": True,
                "fresh_candidate_risk_summary": {"total": {"low": 92, "medium": 3, "high": 1}},
                "fresh_risk_levels": {"manual_confirm": {"low": 1, "medium": 3, "high": 1}},
                "mismatch_codes": ["fresh_source_mismatch", "reference_risk_contract_incomplete"],
            },
        }
    ]

    candidates = golden.summarize_reference_refresh_candidates(rows)

    assert candidates == [
        {
            "case_id": "case-refresh",
            "scenario": "refresh me",
            "reference_job_id": "job-ref",
            "evaluation_job_id": "job-eval",
            "evaluation_mode": "cloned_profile_only",
                "reference_expected_source": "cut_analysis_refine_decision_plan",
                "fresh_source": "variant_timeline_bundle",
                "reference_auto_apply_candidate_count": 0,
                "fresh_auto_apply_candidate_count": 2,
                "reference_rule_auto_apply_cut_count": 0,
                "fresh_rule_auto_apply_cut_count": 92,
                "reference_manual_confirm_candidate_count": 131,
                "fresh_manual_confirm_count": 4,
            "fresh_multimodal_pending_count": 1,
            "fresh_high_risk_cut_count": 1,
            "fresh_llm_reviewed": True,
            "fresh_candidate_risk_summary": {"total": {"low": 92, "medium": 3, "high": 1}},
            "fresh_risk_levels": {"manual_confirm": {"low": 1, "medium": 3, "high": 1}},
            "mismatch_codes": ["fresh_source_mismatch", "reference_risk_contract_incomplete"],
            "refresh_reason": "reference risk contract is incomplete; evaluation snapshot carries the current contract",
        }
    ]


def test_promote_manifest_references_updates_reference_job_and_risk_hints() -> None:
    manifest = {
        "version": "v1",
        "jobs": [
            {
                "case_id": "case-refresh",
                "reference_job_id": "job-ref-old",
                "risk_hints": {
                    "reference_expected_stage": "edit_plan",
                    "reference_expected_source": "cut_analysis_refine_decision_plan",
                    "reference_manual_confirm_candidate_count": 131,
                },
            }
        ],
    }
    batch_report = {
        "reference_refresh_candidates": [
            {
                "case_id": "case-refresh",
                "reference_job_id": "job-ref-old",
                "evaluation_job_id": "job-ref-new",
                "evaluation_mode": "cloned_profile_only",
                "reference_expected_source": "cut_analysis_refine_decision_plan",
                "fresh_source": "variant_timeline_bundle",
                "fresh_auto_apply_candidate_count": 2,
                "fresh_rule_auto_apply_cut_count": 92,
                "fresh_manual_confirm_count": 4,
                "fresh_multimodal_pending_count": 1,
                "fresh_high_risk_cut_count": 1,
                "fresh_candidate_risk_summary": {"total": {"low": 92, "medium": 3, "high": 1}},
                "fresh_risk_levels": {"manual_confirm": {"low": 1, "medium": 3, "high": 1}},
            }
        ],
        "evaluation_risk_snapshots": {
            "case-refresh": {
                "job_id": "job-ref-new",
                "candidate_risk_summary": {"total": {"low": 92, "medium": 3, "high": 1}},
                "risk_levels": {"manual_confirm": {"low": 1, "medium": 3, "high": 1}},
            }
        },
    }

    refreshed_manifest, updates = promote_refs.promote_manifest_references(
        manifest,
        batch_report,
        case_ids=["case-refresh"],
    )

    assert updates == [
        {
            "case_id": "case-refresh",
            "previous_reference_job_id": "job-ref-old",
            "new_reference_job_id": "job-ref-new",
            "new_reference_risk_job_id": None,
            "reference_expected_source": "variant_timeline_bundle",
            "reference_manual_confirm_candidate_count": 4,
            "reference_auto_apply_candidate_count": 2,
            "reference_rule_auto_apply_cut_count": 92,
        }
    ]
    refreshed_job = refreshed_manifest["jobs"][0]
    assert refreshed_job["reference_job_id"] == "job-ref-new"
    assert refreshed_job["risk_hints"] == {
        "reference_expected_stage": "edit_plan",
        "reference_expected_source": "variant_timeline_bundle",
        "reference_manual_confirm_candidate_count": 4,
        "reference_auto_apply_candidate_count": 2,
        "reference_multimodal_pending_count": 1,
        "reference_rule_auto_apply_cut_count": 92,
        "reference_high_risk_cut_count": 1,
        "reference_candidate_risk_summary": {"total": {"low": 92, "medium": 3, "high": 1}},
        "reference_risk_levels": {"manual_confirm": {"low": 1, "medium": 3, "high": 1}},
    }


def test_promote_manifest_references_rejects_unsupported_required_checks() -> None:
    manifest = {
        "version": "v1",
        "jobs": [
            {
                "case_id": "case-refresh",
                "reference_job_id": "job-ref-old",
                "required_checks": ["manual_editor_ready", "unsupported_gate"],
            }
        ],
    }
    batch_report = {
        "reference_refresh_candidates": [
            {
                "case_id": "case-refresh",
                "reference_job_id": "job-ref-old",
                "evaluation_job_id": "job-ref-new",
            }
        ]
    }

    with pytest.raises(ValueError, match="unsupported required_checks"):
        promote_refs.promote_manifest_references(manifest, batch_report)


def test_promote_manifest_references_keeps_manual_editor_reference_job_and_updates_reference_risk_job() -> None:
    manifest = {
        "version": "v1",
        "jobs": [
            {
                "case_id": "case-manual-editor-refresh",
                "reference_job_id": "job-ref-old",
                "required_checks": ["manual_editor_apply_semantics", "subtitle_projection"],
                "risk_hints": {
                    "reference_expected_stage": "edit_plan",
                    "reference_expected_source": "cut_analysis_refine_decision_plan",
                    "reference_manual_confirm_candidate_count": 94,
                },
            }
        ],
    }
    batch_report = {
        "reference_refresh_candidates": [
            {
                "case_id": "case-manual-editor-refresh",
                "reference_job_id": "job-ref-old",
                "evaluation_job_id": "job-risk-new",
                "evaluation_mode": "cloned_profile_only",
                "fresh_source": "variant_timeline_bundle",
                "fresh_auto_apply_candidate_count": 2,
                "fresh_rule_auto_apply_cut_count": 50,
                "fresh_manual_confirm_count": 5,
                "fresh_multimodal_pending_count": 0,
                "fresh_high_risk_cut_count": 0,
                "fresh_candidate_risk_summary": {"total": {"low": 52, "medium": 3, "high": 0}},
                "fresh_risk_levels": {"manual_confirm": {"low": 2, "medium": 3, "high": 0}},
            }
        ],
        "evaluation_risk_snapshots": {
            "case-manual-editor-refresh": {
                "job_id": "job-risk-new",
                "candidate_risk_summary": {"total": {"low": 52, "medium": 3, "high": 0}},
                "risk_levels": {"manual_confirm": {"low": 2, "medium": 3, "high": 0}},
            }
        },
    }

    refreshed_manifest, updates = promote_refs.promote_manifest_references(
        manifest,
        batch_report,
        case_ids=["case-manual-editor-refresh"],
    )

    assert updates == [
        {
            "case_id": "case-manual-editor-refresh",
            "previous_reference_job_id": "job-ref-old",
            "new_reference_job_id": "job-ref-old",
            "new_reference_risk_job_id": "job-risk-new",
            "reference_expected_source": "variant_timeline_bundle",
            "reference_manual_confirm_candidate_count": 5,
            "reference_auto_apply_candidate_count": 2,
            "reference_rule_auto_apply_cut_count": 50,
        }
    ]
    refreshed_job = refreshed_manifest["jobs"][0]
    assert refreshed_job["reference_job_id"] == "job-ref-old"
    assert refreshed_job["reference_risk_job_id"] == "job-risk-new"
    assert refreshed_job["risk_hints"] == {
        "reference_expected_stage": "edit_plan",
        "reference_expected_source": "variant_timeline_bundle",
        "reference_manual_confirm_candidate_count": 5,
        "reference_auto_apply_candidate_count": 2,
        "reference_rule_auto_apply_cut_count": 50,
        "reference_candidate_risk_summary": {"total": {"low": 52, "medium": 3, "high": 0}},
        "reference_risk_levels": {"manual_confirm": {"low": 2, "medium": 3, "high": 0}},
    }


def test_summarize_case_risk_alignment_keeps_non_high_risk_contract_mismatches() -> None:
    rows = [
        {
            "case_id": "case-contract-mismatch",
            "risk_alignment": {
                "reference_high_risk_cut_count": 0,
                "high_risk_reproduced": True,
                "mismatch_codes": ["reference_risk_contract_incomplete"],
            },
        }
    ]

    summary = golden.summarize_case_risk_alignment(rows)

    assert summary == {
        "reference_high_risk_case_count": 0,
        "reproduced_case_count": 0,
        "unreproduced_case_count": 0,
        "mismatch_case_ids": ["case-contract-mismatch"],
        "mismatch_code_counts": {
            "reference_risk_contract_incomplete": 1,
        },
    }


def test_golden_summary_counts_partial_runs_separately() -> None:
    reports = [
        JobRunReport(
            job_id="job-done",
            source_path="E:/done.mp4",
            source_name="done.mp4",
            status="done",
            output_path="E:/done_out.mp4",
            cover_path=None,
            output_duration_sec=12.0,
            transcript_segment_count=4,
            subtitle_count=5,
            correction_count=0,
            keep_ratio=0.5,
            cover_variant_count=0,
            platform_doc=None,
            quality_score=90.0,
            quality_grade="A",
            quality_issue_codes=[],
            live_stage_validations=[],
            content_profile=None,
            steps=[],
            notes=[],
        ),
        JobRunReport(
            job_id="job-partial",
            source_path="E:/partial.mp4",
            source_name="partial.mp4",
            status="partial",
            output_path=None,
            cover_path=None,
            output_duration_sec=0.0,
            transcript_segment_count=0,
            subtitle_count=0,
            correction_count=0,
            keep_ratio=0.0,
            cover_variant_count=0,
            platform_doc=None,
            quality_score=70.0,
            quality_grade="C",
            quality_issue_codes=[],
            live_stage_validations=[],
            content_profile=None,
            steps=[],
            notes=[],
        ),
        JobRunReport(
            job_id="job-failed",
            source_path="E:/failed.mp4",
            source_name="failed.mp4",
            status="failed",
            output_path=None,
            cover_path=None,
            output_duration_sec=0.0,
            transcript_segment_count=0,
            subtitle_count=0,
            correction_count=0,
            keep_ratio=0.0,
            cover_variant_count=0,
            platform_doc=None,
            quality_score=40.0,
            quality_grade="D",
            quality_issue_codes=[],
            live_stage_validations=[],
            content_profile=None,
            steps=[],
            notes=[],
        ),
    ]

    summary = {
        "job_count": len(reports),
        "success_count": sum(1 for report in reports if report.status == "done"),
        "partial_count": sum(1 for report in reports if report.status == "partial"),
        "failed_count": sum(1 for report in reports if report.status == "failed"),
    }

    assert summary == {
        "job_count": 3,
        "success_count": 1,
        "partial_count": 1,
        "failed_count": 1,
    }


def test_derive_effective_job_status_prefers_failed_steps_over_stale_processing_status() -> None:
    status = derive_effective_job_status(
        stored_status="processing",
        step_rows=[
            {"step_name": "probe", "status": "failed", "metadata": {"detail": "下载源视频并准备探测媒体参数"}},
            {"step_name": "content_profile", "status": "pending", "metadata": {}},
        ],
    )

    assert status == "failed"


def test_build_audit_markdown_renders_job_and_step_errors() -> None:
    markdown = build_audit_markdown(
        {
            "job": {
                "id": "job-1",
                "source_name": "demo.mp4",
                "status": "failed",
                "stored_status": "processing",
                "source_path": "E:/missing/demo.mp4",
                "error_message": "Batch full-chain run failed",
                "located_paths": [],
            },
            "step_status": [
                {
                    "step_name": "probe",
                    "status": "failed",
                    "detail": "下载源视频并准备探测媒体参数",
                    "error": "FileNotFoundError: E:/missing/demo.mp4",
                }
            ],
            "artifacts": {
                "counts": {},
                "active_profile_summary": {},
            },
            "heuristics": {
                "issues": [],
            },
        },
        {},
    )

    assert "`stored_job_status`: `processing`" in markdown
    assert "Batch full-chain run failed" in markdown
    assert "error=FileNotFoundError: E:/missing/demo.mp4" in markdown
    assert "先修复源文件定位、挂载路径或本地素材缺失问题，再重跑 `probe`。" in markdown


def test_derive_effective_job_error_falls_back_to_failed_step_error() -> None:
    error = derive_effective_job_error(
        stored_error="",
        step_rows=[
            {"step_name": "probe", "error_message": "FileNotFoundError: E:/missing/demo.mp4"},
        ],
    )

    assert error == "FileNotFoundError: E:/missing/demo.mp4"
